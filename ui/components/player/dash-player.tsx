"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Maximize,
  Minimize,
  Pause,
  Play,
  Settings,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
} from "lucide-react";
import type * as DashJS from "dashjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { connectVideoWs, type VideoWsHandle } from "@/lib/realtime/ws";
import type { WsAbrRecommendation, WsSegmentReport } from "@/lib/types";
import { cn, formatTime } from "@/lib/utils";
import { SeekDownloadOverlay } from "./seek-download-overlay";
import {
  currentAbrMode,
  emptyStreamRendition,
  type StreamRendition,
} from "@/lib/video/rendition";

export interface DashPlayerProps {
  url: string;
  poster?: string;
  /** Enables the server-driven ABR loop over the video WebSocket. */
  videoId?: string;
  className?: string;
  /** Receives a full rendition-telemetry snapshot on every update. */
  onRendition?: (state: StreamRendition) => void;
}

type RenditionSink = ((state: StreamRendition) => void) | null;

/** Merges a patch into the snapshot and forwards it; refs only, so it is safe inside dashjs handlers. */
function pushStream(
  streamRef: { current: StreamRendition },
  sinkRef: { current: RenditionSink },
  patch: Partial<StreamRendition>,
) {
  streamRef.current = { ...streamRef.current, ...patch };
  sinkRef.current?.(streamRef.current);
}

function toMs(value: unknown): number | null {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

function positive(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function applyAbrMode(player: DashJS.MediaPlayerClass, serverDrive: boolean) {
  player.updateSettings({
    streaming: { abr: { autoSwitchBitrate: { video: !serverDrive } } },
  });
}

/**
 * Dev-only handle on the live dash.js instance, so browser-driven probes can turn on
 * dash.js diagnostics and read player state from the page. Never set in production.
 */
const DASH_PLAYER_KEY = "__meridianDashPlayer";

function exposePlayer(player: DashJS.MediaPlayerClass | null) {
  if (process.env.NODE_ENV !== "development") return;
  const w = window as unknown as Record<string, unknown>;
  if (!player) {
    delete w[DASH_PLAYER_KEY];
    return;
  }
  w[DASH_PLAYER_KEY] = player;
  // dashjs.Debug.LOG_LEVEL_INFO — surfaces the internal seek intent logs.
  player.updateSettings({ debug: { logLevel: 4 } });
}

/**
 * Segment length used for the played/downloaded counts before the manifest is
 * known (MPD SegmentTemplate: duration=540000, timescale=90000 → 6s).
 */
const DEFAULT_SEGMENT_SECONDS = 6;

/**
 * The spinner must hold its condition this long before it mounts (ms) — a one-frame
 * blip of the rule never becomes a visible flash. It unmounts the moment it clears.
 */
const BUFFER_SHOW_DELAY_MS = 200;

/**
 * The seek indicator must hold this long before it mounts (ms). A seek that lands in
 * already-buffered media resolves inside the delay, so it never flashes a progress bar.
 */
const SEEK_DOWNLOAD_SHOW_DELAY_MS = 100;

/** An element `waiting` only counts as buffering when <1s of media is really ahead. */
const STALL_HEADROOM_S = 1;

export function DashPlayer({ url, poster, videoId, className, onRendition }: DashPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<DashJS.MediaPlayerClass | null>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<VideoWsHandle | null>(null);
  const wsOpenRef = useRef(false);
  const serverDrivenRef = useRef(true);
  const seqRef = useRef(0);
  const lastAppliedSeqRef = useRef(-1);
  /** Counts every rendered media segment for display (unlike seqRef, which only counts sent reports). */
  const segIndexRef = useRef(0);
  const streamRef = useRef<StreamRendition>(emptyStreamRendition());
  const sinkRef = useRef<RenditionSink>(null);
  /** Segment duration (seconds) — refreshed from the manifest when known. */
  const segDurRef = useRef(DEFAULT_SEGMENT_SECONDS);
  /** Last real download edge (s) — kept when both buffer metrics are missing/stale. */
  const lastBufferedEndRef = useRef(0);
  /** Pending 200ms show-timer for the buffering spinner. */
  const showTimerRef = useRef<number | null>(null);
  /** Pointer ratio while dragging the seek bar (null = idle). */
  const [scrubRatio, setScrubRatio] = useState<number | null>(null);
  const draggingRef = useRef(false);
  const scrubRafRef = useRef<number | null>(null);
  const pendingSeekRef = useRef<number | null>(null);
  /** Dash.js handlers read this instead of state, so they never see a stale closure. */
  const seekingRef = useRef(false);
  /** Seek target the last `playbackSeeking` reported — used to pick its segment. */
  const seekTargetRef = useRef<number | null>(null);
  /** Pending show-timer for the seek download indicator. */
  const seekShowTimerRef = useRef<number | null>(null);

  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  /** Element raised `waiting` (cannot continue) and has not resumed yet. */
  const [stalling, setStalling] = useState(false);
  /** The spinner rule held for `BUFFER_SHOW_DELAY_MS` — display adds `&& rawBuffering`. */
  const [showBuffering, setShowBuffering] = useState(false);
  /** A seek is in flight and the element has not reached the new position yet. */
  const [seeking, setSeeking] = useState(false);
  /** Byte progress of the segment that seek is waiting on — `percent` null means indeterminate. */
  const [seekDownload, setSeekDownload] = useState({
    percent: null as number | null,
    loaded: 0,
    total: 0,
  });
  /** The seek rule held for `SEEK_DOWNLOAD_SHOW_DELAY_MS` — display adds `&& seeking`. */
  const [showSeekDownload, setShowSeekDownload] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffer, setBuffer] = useState(0);
  /** Total played / downloaded segment time in seconds (+ raw download edge). */
  const [segments, setSegments] = useState({
    playedTime: 0,
    downloadedTime: 0,
    bufferedEnd: 0,
  });
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [levels, setLevels] = useState<{ id: string; label: string }[]>([]);
  const [level, setLevel] = useState<string>("auto");
  const [showSettings, setShowSettings] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    sinkRef.current = onRendition ?? null;
    return () => {
      sinkRef.current = null;
    };
  }, [onRendition]);

  const applyRecommendation = useCallback(
    (rec: WsAbrRecommendation) => {
      console.log("[ws ← abr_recommendation]", JSON.stringify(rec));
      const p = playerRef.current;
      if (!p || !videoId) return;
      if (rec.video_id !== videoId) return;
      if (rec.seq <= lastAppliedSeqRef.current) return;
      lastAppliedSeqRef.current = rec.seq;
      pushStream(streamRef, sinkRef, {
        recommendation: {
          current: rec.current_rendition,
          recommended: rec.recommended_rendition,
          reason: rec.reason,
        },
      });
      if (!serverDrivenRef.current) return;
      if (rec.recommended_rendition === rec.current_rendition) return;
      try {
        const target = p
          .getRepresentationsByType("video")
          .find((r) => `${r.height}p` === rec.recommended_rendition);
        if (!target) return;
        // forceReplace=false: the switch applies on the next segment download
        p.setRepresentationForTypeById("video", target.id, false);
      } catch {
        /* ignore */
      }
    },
    [videoId],
  );

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !url) return;
    let active = true;
    let player: DashJS.MediaPlayerClass | null = null;
    let videoEl: HTMLVideoElement | null = null;
    const nativeReadyHandlers: { type: string; handler: () => void }[] = [];
    setReady(false);
    setError(null);
    setPlaying(false);
    setStalling(false);
    setLevels([]);
    segIndexRef.current = 0;
    segDurRef.current = DEFAULT_SEGMENT_SECONDS;
    lastBufferedEndRef.current = 0;
    if (showTimerRef.current !== null) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    seekingRef.current = false;
    seekTargetRef.current = null;
    setSeeking(false);
    setShowSeekDownload(false);
    setSeekDownload({ percent: null, loaded: 0, total: 0 });
    if (seekShowTimerRef.current !== null) {
      clearTimeout(seekShowTimerRef.current);
      seekShowTimerRef.current = null;
    }
    setSegments({ playedTime: 0, downloadedTime: 0, bufferedEnd: 0 });
    pushStream(streamRef, sinkRef, {
      ...emptyStreamRendition(),
      mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
    });

    const initializePlayer = async () => {
      try {
        const dashjs = await import("dashjs");
        if (!active) return;

        videoEl = root.querySelector("video");
        if (!videoEl) {
          videoEl = document.createElement("video");
          videoEl.setAttribute("playsinline", "");
          root.appendChild(videoEl);
        }

        player = dashjs.MediaPlayer().create();
        playerRef.current = player;
        exposePlayer(player);
        const mp: DashJS.MediaPlayerClass = player;
        player.initialize(videoEl, url, false);
        player.updateSettings({
          streaming: {
            abr: { autoSwitchBitrate: { video: true } },
            buffer: { fastSwitchEnabled: true },
          },
        });
        seqRef.current = 0;
        lastAppliedSeqRef.current = -1;
        applyAbrMode(mp, serverDrivenRef.current && wsOpenRef.current);

        const events = dashjs.MediaPlayer.events as unknown as Record<string, string>;
        const markReady = () => {
          setReady(true);
          setError(null);
          try {
            const reps = (
              player as unknown as {
                getRepresentationsByType?: (type: string) => {
                  id: string;
                  height?: number;
                  fragmentDuration?: number | null;
                }[];
              }
            ).getRepresentationsByType?.("video") ?? [];
            const nextLevels = reps
              .filter((r) => r.height)
              .map((r) => ({ id: String(r.id), label: `${r.height}p` }));
            setLevels(nextLevels);
            pushStream(streamRef, sinkRef, { ladder: nextLevels });
            const segDur = reps.find(
              (r) => typeof r.fragmentDuration === "number" && r.fragmentDuration > 0,
            )?.fragmentDuration;
            if (typeof segDur === "number" && segDur > 0) segDurRef.current = segDur;
          } catch {
            /* ignore */
          }
        };
        const onPlaybackError = (e?: { error?: { message?: string } }) => {
          setError(e?.error?.message || "Playback failed");
          setReady(false);
        };
        /**
         * Recompute total played segment time, total downloaded segment time and
         * the raw download edge (farthest media appended). `timeupdate` stops while
         * playback is blocked, so this also runs off buffer/seek/resume events.
         */
        const syncSegments = () => {
          if (!player) return;
          const t = player.time();
          let bufferedEnd: number | null = null;
          try {
            // Per-track buffer level first: element.buffered is the audio∩video
            // intersection and lags the video download edge (audio trails it).
            const ahead = (
              mp as unknown as { getBufferLength?: (type: string) => number }
            ).getBufferLength?.("video");
            if (typeof ahead === "number" && Number.isFinite(ahead)) {
              bufferedEnd = t + Math.max(0, ahead);
            }
            const range = (
              mp as unknown as { getBufferRange?: () => TimeRanges | null }
            ).getBufferRange?.();
            if (range && range.length > 0) {
              for (let i = 0; i < range.length; i += 1) {
                const end = range.end(i);
                if (!Number.isFinite(end)) continue;
                bufferedEnd = bufferedEnd === null ? end : Math.max(bufferedEnd, end);
              }
            }
          } catch {
            bufferedEnd = null;
          }
          // Never collapse to the playhead: with both metrics missing/stale that would
          // fabricate playedTime === downloadedTime. Keep the last real edge instead.
          if (bufferedEnd === null) {
            bufferedEnd = lastBufferedEndRef.current;
          } else {
            lastBufferedEndRef.current = bufferedEnd;
          }
          const ahead = Math.max(0, bufferedEnd - t);
          setBuffer((prev) => (prev === ahead ? prev : ahead));
          const segDur = segDurRef.current > 0 ? segDurRef.current : DEFAULT_SEGMENT_SECONDS;
          const next = {
            playedTime: Math.floor(t / segDur) * segDur,
            downloadedTime: Math.floor(bufferedEnd / segDur) * segDur,
            bufferedEnd,
          };
          setSegments((prev) =>
            prev.playedTime === next.playedTime &&
            prev.downloadedTime === next.downloadedTime &&
            prev.bufferedEnd === next.bufferedEnd
              ? prev
              : next,
          );
        };
        const onTime = () => {
          if (!player) return;
          setCurrent(player.time());
          // The clock advanced, so playback is no longer blocked.
          setStalling(false);
          syncSegments();
        };
        const onDuration = () => {
          if (player) setDuration(player.duration());
        };
        const onPlayState = () => {
          if (player) setPlaying(!player.isPaused());
        };
        /** dash.js `waiting` = the element cannot continue; `playing`/`seeked` = resumed. */
        const onStall = () => {
          setStalling(true);
          syncSegments();
        };
        const onResume = () => {
          setStalling(false);
          // Bound to `playbackSeeked` and `playbackPlaying` below — either one ends a seek.
          seekingRef.current = false;
          setSeeking(false);
          syncSegments();
        };
        /** dash.js seek start; the initial internal seek does not dispatch this. */
        const onSeeking = (e: { seekTime?: number | null }) => {
          seekingRef.current = true;
          seekTargetRef.current =
            typeof e?.seekTime === "number" && Number.isFinite(e.seekTime) ? e.seekTime : null;
          setSeeking(true);
          setSeekDownload({ percent: null, loaded: 0, total: 0 });
        };
        /**
         * Live byte progress of the in-flight segment (`CoreEvents.LOADING_PROGRESS`, fired on
         * every XHR tick). Scoped to the current seek so background buffer fill never reaches
         * the indicator, and matched to the segment the seek actually targets.
         */
        const onLoadingProgress = (e: {
          request?: {
            type?: string;
            mediaType?: string;
            mediaStartTime?: number;
            duration?: number;
            bytesLoaded?: number;
            bytesTotal?: number;
          };
        }) => {
          if (!seekingRef.current) return;
          const req = e?.request;
          if (!req || req.type !== "MediaSegment") return;
          if (req.mediaType && req.mediaType !== "video") return;

          const target = seekTargetRef.current;
          const start = req.mediaStartTime;
          const span = req.duration;
          if (target !== null && typeof start === "number" && Number.isFinite(start)) {
            const end = typeof span === "number" && span > 0 ? start + span : start;
            // Not the segment covering the seek target (its bounds are known).
            if (target < start || target >= end) return;
          }

          const total = positive(req.bytesTotal);
          const loaded = positive(req.bytesLoaded);
          // No Content-Length: keep the percent null so the overlay shows an indeterminate bar.
          const percent = total !== null && loaded !== null ? Math.min(100, (loaded / total) * 100) : null;
          const rounded = percent === null ? null : Math.round(percent);

          // This fires many times a second — only re-render when the integer actually moves.
          setSeekDownload((prev) =>
            prev.percent === rounded && prev.loaded === (loaded ?? 0) && prev.total === (total ?? 0)
              ? prev
              : { percent: rounded, loaded: loaded ?? 0, total: total ?? 0 },
          );
        };

        for (const evt of ["loadedmetadata", "canplay"] as const) {
          const handler = () => markReady();
          videoEl?.addEventListener(evt, handler);
          nativeReadyHandlers.push({ type: evt, handler });
        }
        const onFragmentLoaded = (e: {
          request?: {
            type?: string;
            bytesTotal?: number;
            bytesLoaded?: number;
            startDate?: Date | number;
            firstByteDate?: Date | number;
            requestEndDate?: Date | number;
            /** dash.js stamps this on completion; the bundled .d.ts still declares requestEndDate. */
            endDate?: Date | number | null;
          };
        }) => {
          syncSegments();
          const req = e?.request;
          if (!req || req.type !== "MediaSegment") return;
          try {
            const start = toMs(req.startDate);
            const firstByte = toMs(req.firstByteDate);
            const end = toMs(req.endDate ?? req.requestEndDate);
            const bytes = positive(req.bytesTotal) ?? positive(req.bytesLoaded);
            if (start === null || end === null || bytes === null) return;
            const segDownloadTime = (end - start) / 1000;
            if (!(segDownloadTime > 0)) return;
            const height = mp.getCurrentRepresentationForType("video")?.height;
            let bufferLength = 0;
            try {
              bufferLength = mp.getBufferLength("video") || 0;
            } catch {
              /* keep 0 */
            }
            const bandwidth = Math.round((bytes * 8) / segDownloadTime);

            // Display path runs for every segment, socket open or not.
            pushStream(streamRef, sinkRef, {
              mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
              rendition: height ? `${height}p` : streamRef.current.rendition,
              segmentIndex: ++segIndexRef.current,
              bandwidthBps: bandwidth,
              downloadMs: Math.round(segDownloadTime * 1000),
              bufferSec: Math.round(bufferLength * 10) / 10,
            });

            // Report path: server-driven ABR only.
            if (!videoId || !serverDrivenRef.current || !wsOpenRef.current) return;
            const ws = wsRef.current;
            if (!ws || !height) return;
            const report: WsSegmentReport = {
              type: "segment_report",
              video_id: videoId,
              seq: seqRef.current++,
              bandwidth,
              latency:
                firstByte !== null && firstByte >= start ? (firstByte - start) / 1000 : 0,
              seg_download_time: segDownloadTime,
              current_buffer_duration: bufferLength,
              current_rendition: `${height}p`,
            };
            console.log("[ws → segment_report]", JSON.stringify(report));
            ws.send(report);
          } catch {
            /* ignore malformed metrics */
          }
        };
        const onQualityRendered = (e: { mediaType?: string; newQuality?: number }) => {
          if (e?.mediaType && e.mediaType !== "video") return;
          try {
            const height = mp.getCurrentRepresentationForType("video")?.height;
            if (serverDrivenRef.current) {
              setLevel("auto");
            } else {
              const reps = mp.getRepresentationsByType("video");
              const id =
                typeof e?.newQuality === "number" ? reps[e.newQuality]?.id : undefined;
              if (id !== undefined) setLevel(String(id));
            }
            pushStream(streamRef, sinkRef, {
              mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
              rendition: height ? `${height}p` : streamRef.current.rendition,
            });
          } catch {
            /* ignore */
          }
        };

        player.on(events.STREAM_INITIALIZED ?? "streamInitialized", markReady);
        player.on(events.CAN_PLAY ?? "canPlay", markReady);
        player.on(events.PLAYBACK_STARTED ?? "playbackStarted", markReady);
        player.on(events.ERROR ?? "error", onPlaybackError as never);
        player.on(events.PLAYBACK_TIME_UPDATED ?? "playbackTimeUpdated", onTime);
        player.on(events.PLAYBACK_METADATA_LOADED ?? "playbackMetadataLoaded", onDuration);
        player.on(events.PLAYBACK_STARTED ?? "playbackStarted", onPlayState);
        player.on(events.PLAYBACK_PAUSED ?? "playbackPaused", onPlayState);
        player.on(events.PLAYBACK_ENDED ?? "playbackEnded", onPlayState);
        player.on(
          events.FRAGMENT_LOADING_COMPLETED ?? "fragmentLoadingCompleted",
          onFragmentLoaded as never,
        );
        player.on(
          events.QUALITY_CHANGE_RENDERED ?? "qualityChangeRendered",
          onQualityRendered as never,
        );
        // The element stops firing timeupdate while playback is blocked, so the
        // buffering readout also refreshes on buffer, seek, stall and resume.
        player.on(events.BUFFER_LEVEL_UPDATED ?? "bufferLevelUpdated", syncSegments);
        player.on(events.PLAYBACK_WAITING ?? "playbackWaiting", onStall);
        player.on(events.PLAYBACK_SEEKING ?? "playbackSeeking", onSeeking as never);
        player.on(events.PLAYBACK_SEEKED ?? "playbackSeeked", onResume);
        player.on(events.PLAYBACK_PLAYING ?? "playbackPlaying", onResume);
        // Core event, deliberately not on MediaPlayer.events — subscribe by its literal name.
        player.on("loadingProgress", onLoadingProgress as never);
        // Playback just (re)started — refresh the counts, not only the ready/playing flags.
        player.on(events.PLAYBACK_STARTED ?? "playbackStarted", syncSegments);
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : "Could not load playback library");
        }
      }
    };

    void initializePlayer();

    return () => {
      active = false;
      for (const { type, handler } of nativeReadyHandlers) {
        videoEl?.removeEventListener(type, handler);
      }
      nativeReadyHandlers.length = 0;
      try {
        player?.reset();
      } catch {
        /* ignore */
      }
      if (playerRef.current === player) playerRef.current = null;
      exposePlayer(null);
    };
  }, [url, videoId]);

  useEffect(() => {
    if (!videoId) return;
    const handle = connectVideoWs(
      () => {
        /* status pushes belong to the page's own socket — ignore here */
      },
      (s) => {
        wsOpenRef.current = s === "open";
        const p = playerRef.current;
        if (p && serverDrivenRef.current) applyAbrMode(p, wsOpenRef.current);
        pushStream(streamRef, sinkRef, {
          mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
        });
      },
      applyRecommendation,
    );
    wsRef.current = handle;
    const p = playerRef.current;
    if (p && serverDrivenRef.current) applyAbrMode(p, wsOpenRef.current);
    pushStream(streamRef, sinkRef, {
      mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
    });
    return () => {
      handle.close();
      if (wsRef.current === handle) wsRef.current = null;
      wsOpenRef.current = false;
      const pl = playerRef.current;
      if (pl && serverDrivenRef.current) applyAbrMode(pl, false);
    };
  }, [videoId, applyRecommendation]);

  const togglePlay = useCallback(() => {
    const p = playerRef.current;
    if (!p) return;
    if (p.isPaused()) void p.play();
    else p.pause();
  }, []);

  const seekBy = useCallback((delta: number) => {
    const p = playerRef.current;
    if (!p) return;
    const next = Math.max(0, Math.min(p.duration(), p.time() + delta));
    p.seek(next);
  }, []);

  const seekTo = useCallback((t: number) => {
    // Optimistic: the bar must not snap back while the seek is in flight.
    setCurrent(t);
    playerRef.current?.seek(t);
  }, []);

  /** Client X → 0..1 ratio across the track. */
  const scrubTargetFrom = useCallback((el: HTMLElement, clientX: number) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  }, []);

  /** Live drag: bar follows the pointer, seeks are rAF-throttled. */
  const applyScrub = useCallback(
    (ratio: number) => {
      setScrubRatio(ratio);
      if (duration <= 0) return;
      pendingSeekRef.current = ratio * duration;
      if (scrubRafRef.current !== null) return;
      scrubRafRef.current = requestAnimationFrame(() => {
        scrubRafRef.current = null;
        const target = pendingSeekRef.current;
        pendingSeekRef.current = null;
        if (target !== null) seekTo(target);
      });
    },
    [duration, seekTo],
  );

  /** Release: commit the final position and hand the bar back to `current`. */
  const endScrub = useCallback(
    (el: HTMLElement | null, clientX: number) => {
      draggingRef.current = false;
      if (scrubRafRef.current !== null) {
        cancelAnimationFrame(scrubRafRef.current);
        scrubRafRef.current = null;
      }
      pendingSeekRef.current = null;
      // scrubTargetFrom yields a 0..1 ratio; seekTo takes seconds.
      if (el && duration > 0) {
        seekTo(scrubTargetFrom(el, clientX) * duration);
      }
      setScrubRatio(null);
    },
    [duration, seekTo, scrubTargetFrom],
  );

  useEffect(
    () => () => {
      if (scrubRafRef.current !== null) cancelAnimationFrame(scrubRafRef.current);
    },
    [],
  );

  const toggleMute = useCallback(() => {
    const p = playerRef.current;
    if (!p) return;
    const next = !muted;
    p.setMute(next);
    setMuted(next);
  }, [muted]);

  const changeVolume = useCallback((v: number) => {
    const p = playerRef.current;
    if (!p) return;
    p.setVolume(v);
    setVolume(v);
    setMuted(v === 0);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const el = shellRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      await el.requestFullscreen();
      setFullscreen(true);
    } else {
      await document.exitFullscreen();
      setFullscreen(false);
    }
  }, []);

  const changeLevel = useCallback((id: string) => {
    const p = playerRef.current;
    if (!p) return;
    setLevel(id);
    serverDrivenRef.current = id === "auto";
    if (id === "auto") {
      // Auto = server-driven while the socket is open, dashjs fallback otherwise
      applyAbrMode(p, wsOpenRef.current);
    } else {
      // Manual pick: suppress server recommendations and jump immediately
      p.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: false } } } });
      p.setRepresentationForTypeById("video", id, true);
    }
    pushStream(streamRef, sinkRef, {
      mode: currentAbrMode(serverDrivenRef.current, wsOpenRef.current),
    });
    setShowSettings(false);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowRight") seekBy(5);
      else if (e.code === "ArrowLeft") seekBy(-5);
      else if (e.key === "m") toggleMute();
      else if (e.key === "f") void toggleFullscreen();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlay, seekBy, toggleMute, toggleFullscreen]);

  const bumpControls = useCallback(() => {
    setControlsVisible(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => {
      if (playerRef.current && !playerRef.current.isPaused()) setControlsVisible(false);
    }, 2800);
  }, []);

  const progress = duration > 0 ? (current / duration) * 100 : 0;
  /** Percent drawn on the bar — the pointer ratio while dragging. */
  const shownProgress = scrubRatio !== null ? scrubRatio * 100 : progress;
  const buffered = duration > 0 ? Math.min(100, (current + buffer) / duration * 100) : 0;
  /** Whole video already appended — never a buffering state (rule: downloaded time != duration). */
  const fullyDownloaded = duration > 0 && Math.abs(segments.bufferedEnd - duration) <= 0.5;
  /** Seconds of media actually ahead of the playhead (never negative). */
  const headroom = Math.max(0, segments.bufferedEnd - current);
  /**
   * Spinner rule: total played segment time == total downloaded segment time (and the
   * download is not the whole file) — or the element raised `waiting` while less than a
   * second of media is really ahead, i.e. a boundary stall where the freshly-crossed
   * segment keeps the two counts one step apart. A bare `waiting` with seconds of
   * headroom (seek, resume, gap jump) is not buffering.
   */
  const ruleMet =
    segments.playedTime === segments.downloadedTime ||
    (stalling && headroom < STALL_HEADROOM_S);
  const rawBuffering = ready && !error && playing && !fullyDownloaded && ruleMet;

  /**
   * Seek indicator: still seeking, held past SEEK_DOWNLOAD_SHOW_DELAY_MS, and no longer
   * dragging — while the pointer is down the scrub UI (moving bar + time tooltip) is itself
   * the feedback, so the overlay waits for release to avoid a bouncing percentage.
   */
  const seekDownloadActive = showSeekDownload && seeking && scrubRatio === null;

  /**
   * Debounce: mount only after `rawBuffering` held for BUFFER_SHOW_DELAY_MS continuously
   * (a one-frame blip of the rule never becomes a flash), unmount the frame it clears.
   * The seek indicator wins outright so the two never stack.
   */
  const buffering = showBuffering && rawBuffering && !seekDownloadActive;
  useEffect(() => {
    if (!rawBuffering) {
      if (showTimerRef.current !== null) {
        clearTimeout(showTimerRef.current);
        showTimerRef.current = null;
      }
      if (showBuffering) {
        const id = window.setTimeout(() => setShowBuffering(false), 0);
        return () => clearTimeout(id);
      }
      return undefined;
    }
    if (showBuffering || showTimerRef.current !== null) return undefined;
    showTimerRef.current = window.setTimeout(() => {
      showTimerRef.current = null;
      setShowBuffering(true);
    }, BUFFER_SHOW_DELAY_MS);
    return () => {
      if (showTimerRef.current !== null) {
        clearTimeout(showTimerRef.current);
        showTimerRef.current = null;
      }
    };
  }, [rawBuffering, showBuffering]);

  /** Same debounce shape as buffering, driven by the seek instead. */
  useEffect(() => {
    if (!seeking || scrubRatio !== null) {
      if (seekShowTimerRef.current !== null) {
        clearTimeout(seekShowTimerRef.current);
        seekShowTimerRef.current = null;
      }
      if (showSeekDownload) {
        const id = window.setTimeout(() => setShowSeekDownload(false), 0);
        return () => clearTimeout(id);
      }
      return undefined;
    }
    if (showSeekDownload || seekShowTimerRef.current !== null) return undefined;
    seekShowTimerRef.current = window.setTimeout(() => {
      seekShowTimerRef.current = null;
      setShowSeekDownload(true);
    }, SEEK_DOWNLOAD_SHOW_DELAY_MS);
    return () => {
      if (seekShowTimerRef.current !== null) {
        clearTimeout(seekShowTimerRef.current);
        seekShowTimerRef.current = null;
      }
    };
  }, [seeking, showSeekDownload, scrubRatio]);

  return (
    <div
      ref={shellRef}
      data-buffering={String(buffering)}
      data-buffering-raw={String(rawBuffering)}
      data-stalling={String(stalling)}
      data-seeking={String(seeking)}
      data-seek-download={String(seekDownloadActive)}
      data-seek-percent={seekDownload.percent ?? ""}
      data-headroom={Math.round(headroom * 100) / 100}
      data-scrubbing={String(scrubRatio !== null)}
      data-played-time={segments.playedTime}
      data-downloaded-time={segments.downloadedTime}
      data-buffered-end={Math.round(segments.bufferedEnd * 100) / 100}
      data-duration={Math.round(duration * 100) / 100}
      className={cn(
        "group relative overflow-hidden rounded-xl border border-zinc-800 bg-black",
        className,
      )}
      onMouseMove={bumpControls}
      onMouseLeave={() => {
        if (playerRef.current && !playerRef.current.isPaused()) setControlsVisible(false);
      }}
    >
      <div
        ref={containerRef}
        className="aspect-video w-full [&_video]:h-full [&_video]:w-full"
        onClick={togglePlay}
      />

      <AnimatePresence>
        {buffering && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.1 }}
            role="status"
            data-testid="buffering-overlay"
            className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-black/40"
          >
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
            <p className="text-sm text-zinc-300">Buffering…</p>
          </motion.div>
        )}
      </AnimatePresence>

      <SeekDownloadOverlay visible={seekDownloadActive} percent={seekDownload.percent} />

      <AnimatePresence>
        {!ready && !error && (
          <motion.div
            initial={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-zinc-950/80"
          >
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
            <p className="text-sm text-zinc-400">Loading stream…</p>
            {poster && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={poster} alt="" className="absolute inset-0 -z-10 h-full w-full object-cover opacity-20" />
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-zinc-950/90 p-6 text-center">
          <p className="font-medium text-red-400">Playback unavailable</p>
          <p className="text-sm text-zinc-400">{error}</p>
        </div>
      )}

      {!playing && ready && !error && (
        <button
          type="button"
          onClick={togglePlay}
          className="absolute inset-0 flex items-center justify-center bg-black/30"
          aria-label="Play"
        >
          <motion.span
            initial={{ scale: 0.85, opacity: 0.8 }}
            animate={{ scale: 1, opacity: 1 }}
            className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-500 text-white shadow-[0_0_40px_-8px_rgba(51,88,255,0.8)]"
          >
            <Play className="h-7 w-7 translate-x-0.5" fill="currentColor" />
          </motion.span>
        </button>
      )}

      <motion.div
        animate={{ opacity: controlsVisible || !playing ? 1 : 0, y: controlsVisible || !playing ? 0 : 8 }}
        transition={{ duration: 0.2 }}
        className="absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black via-black/80 to-transparent px-3 pb-3 pt-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="relative mb-2 h-1.5 cursor-pointer touch-none select-none rounded-full bg-white/15"
          role="slider"
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={duration || 0}
          aria-valuenow={
            scrubRatio !== null ? Math.round(scrubRatio * duration * 10) / 10 : current
          }
          tabIndex={0}
          onPointerDown={(e) => {
            if (duration <= 0) return;
            e.preventDefault();
            e.currentTarget.setPointerCapture(e.pointerId);
            e.currentTarget.focus();
            draggingRef.current = true;
            applyScrub(scrubTargetFrom(e.currentTarget, e.clientX));
          }}
          onPointerMove={(e) => {
            if (!draggingRef.current) return;
            applyScrub(scrubTargetFrom(e.currentTarget, e.clientX));
          }}
          onPointerUp={(e) => {
            if (!draggingRef.current) return;
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
              e.currentTarget.releasePointerCapture(e.pointerId);
            }
            endScrub(e.currentTarget, e.clientX);
          }}
          onPointerCancel={(e) => {
            if (!draggingRef.current) return;
            endScrub(e.currentTarget, e.clientX);
          }}
          onKeyDown={(e) => {
            // The window handler below also seeks on arrows; without this the
            // slider (focused by pointerdown) would seek twice per press.
            if (e.key === "ArrowRight" || e.key === "ArrowLeft") e.stopPropagation();
            if (e.key === "ArrowRight") seekBy(5);
            if (e.key === "ArrowLeft") seekBy(-5);
          }}
        >
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-white/25"
            style={{ width: `${buffered}%` }}
          />
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-brand-500"
            style={{ width: `${shownProgress}%` }}
          />
          <span
            className={cn(
              "absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full bg-white shadow transition-opacity group-hover:opacity-100",
              scrubRatio === null && "opacity-0",
            )}
            style={{ left: `${shownProgress}%` }}
          />
          {scrubRatio !== null && (
            <span
              className="pointer-events-none absolute -top-7 -translate-x-1/2 whitespace-nowrap rounded bg-black/85 px-1.5 py-0.5 font-mono text-[11px] text-white"
              style={{ left: `${shownProgress}%` }}
            >
              {formatTime(scrubRatio * duration)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 text-white">
          <button
            type="button"
            onClick={togglePlay}
            className="rounded-lg p-1.5 hover:bg-white/10"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
          </button>
          <button
            type="button"
            onClick={() => seekBy(-10)}
            className="rounded-lg p-1.5 hover:bg-white/10"
            aria-label="Back 10s"
          >
            <SkipBack className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => seekBy(10)}
            className="rounded-lg p-1.5 hover:bg-white/10"
            aria-label="Forward 10s"
          >
            <SkipForward className="h-4 w-4" />
          </button>

          <div className="ml-1 flex items-center gap-1.5">
            <button
              type="button"
              onClick={toggleMute}
              className="rounded-lg p-1.5 hover:bg-white/10"
              aria-label={muted ? "Unmute" : "Mute"}
            >
              {muted || volume === 0 ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => changeVolume(Number(e.target.value))}
              className="h-1 w-16 accent-brand-500"
              aria-label="Volume"
            />
          </div>

          <span className="ml-1 font-mono text-[11px] text-zinc-300">
            {formatTime(current)} / {formatTime(duration)}
          </span>

          <div className="ml-auto flex items-center gap-1">
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSettings((s) => !s)}
                className="rounded-lg p-1.5 hover:bg-white/10"
                aria-label="Quality settings"
                aria-expanded={showSettings}
              >
                <Settings className="h-4 w-4" />
              </button>
              <AnimatePresence>
                {showSettings && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 6 }}
                    className="absolute bottom-10 right-0 min-w-[120px] overflow-hidden rounded-lg border border-zinc-700 bg-zinc-900/95 py-1 shadow-xl"
                  >
                    <button
                      type="button"
                      onClick={() => changeLevel("auto")}
                      className={cn(
                        "block w-full px-3 py-1.5 text-left text-xs hover:bg-zinc-800",
                        level === "auto" && "text-brand-400",
                      )}
                    >
                      Auto
                    </button>
                    {levels.map((l) => (
                      <button
                        key={l.id}
                        type="button"
                        onClick={() => changeLevel(l.id)}
                        className={cn(
                          "block w-full px-3 py-1.5 text-left text-xs hover:bg-zinc-800",
                          level === l.id && "text-brand-400",
                        )}
                      >
                        {l.label}
                      </button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            <button
              type="button"
              onClick={() => void toggleFullscreen()}
              className="rounded-lg p-1.5 hover:bg-white/10"
              aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
            >
              {fullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
