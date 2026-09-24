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
import * as dashjs from "dashjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn, formatTime } from "@/lib/utils";

export interface DashPlayerProps {
  url: string;
  poster?: string;
  className?: string;
}

export function DashPlayer({ url, poster, className }: DashPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<dashjs.MediaPlayerClass | null>(null);
  const shellRef = useRef<HTMLDivElement>(null);

  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffer, setBuffer] = useState(0);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [levels, setLevels] = useState<{ id: string; label: string }[]>([]);
  const [level, setLevel] = useState<string>("auto");
  const [showSettings, setShowSettings] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !url) return;
    let videoEl = root.querySelector("video");
    if (!videoEl) {
      videoEl = document.createElement("video");
      videoEl.setAttribute("playsinline", "");
      root.appendChild(videoEl);
    }

    const player = dashjs.MediaPlayer().create();
    playerRef.current = player;
    player.initialize(videoEl, url, false);
    player.updateSettings({
      streaming: {
        abr: { autoSwitchBitrate: { video: true } },
        buffer: { fastSwitchEnabled: true },
      },
    });

    const events = dashjs.MediaPlayer.events as unknown as Record<string, string>;
    const onReady = () => {
      setReady(true);
      setError(null);
      try {
        const ls = (
          player as unknown as { getLevels?: () => { id: number; height?: number }[] }
        ).getLevels?.() ?? [];
        setLevels(
          ls
            .filter((l) => l.height)
            .map((l) => ({ id: String(l.id), label: `${l.height}p` })),
        );
      } catch {
        /* ignore */
      }
    };
    const onPlaybackError = (e?: { error?: { message?: string } }) => {
      setError(e?.error?.message || "Playback failed");
      setReady(false);
    };
    const onTime = () => {
      setCurrent(player.time());
      try {
        const getBuffer = (
          player as unknown as { getBufferLength?: (t: number) => number }
        ).getBufferLength;
        const ranges = getBuffer?.call(player, 0);
        if (typeof ranges === "number") setBuffer(ranges);
      } catch {
        /* ignore */
      }
    };
    const onDuration = () => setDuration(player.duration());
    const onPlayState = () => setPlaying(!player.isPaused());

    player.on(events.READY ?? "ready", onReady);
    player.on(events.ERROR ?? "error", onPlaybackError as never);
    player.on(events.PLAYBACK_TIME_UPDATED ?? "playbackTimeUpdated", onTime);
    player.on(events.PLAYBACK_METADATA_LOADED ?? "playbackMetadataLoaded", onDuration);
    player.on(events.PLAYBACK_STARTED ?? "playbackStarted", onPlayState);
    player.on(events.PLAYBACK_PAUSED ?? "playbackPaused", onPlayState);
    player.on(events.PLAYBACK_ENDED ?? "playbackEnded", onPlayState);

    return () => {
      try {
        player.reset();
      } catch {
        /* ignore */
      }
      playerRef.current = null;
    };
  }, [url]);

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
    playerRef.current?.seek(t);
  }, []);

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
    if (id === "auto") {
      p.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: true } } } });
    } else {
      p.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: false } } } });
      const setQ = (
        p as unknown as {
          setQualityFor?: (type: string, quality: number, download?: boolean) => void;
        }
      ).setQualityFor;
      setQ?.call(p, "video", Number(id), true);
    }
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
  const buffered = duration > 0 ? Math.min(100, (current + buffer) / duration * 100) : 0;

  return (
    <div
      ref={shellRef}
      className={cn(
        "group relative overflow-hidden rounded-2xl border border-zinc-800 bg-black",
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
            className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-500 text-white shadow-[0_0_40px_-8px_rgba(239,25,42,0.8)]"
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
          className="relative mb-2 h-1.5 cursor-pointer rounded-full bg-white/15"
          role="slider"
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={duration || 0}
          aria-valuenow={current}
          tabIndex={0}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            seekTo(ratio * duration);
          }}
          onKeyDown={(e) => {
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
            style={{ width: `${progress}%` }}
          />
          <span
            className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full bg-white opacity-0 shadow transition-opacity group-hover:opacity-100"
            style={{ left: `${progress}%` }}
          />
        </div>

        <div className="flex items-center gap-2 text-white">
          <button
            type="button"
            onClick={togglePlay}
            className="rounded-md p-1.5 hover:bg-white/10"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
          </button>
          <button
            type="button"
            onClick={() => seekBy(-10)}
            className="rounded-md p-1.5 hover:bg-white/10"
            aria-label="Back 10s"
          >
            <SkipBack className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => seekBy(10)}
            className="rounded-md p-1.5 hover:bg-white/10"
            aria-label="Forward 10s"
          >
            <SkipForward className="h-4 w-4" />
          </button>

          <div className="ml-1 flex items-center gap-1.5">
            <button
              type="button"
              onClick={toggleMute}
              className="rounded-md p-1.5 hover:bg-white/10"
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
                className="rounded-md p-1.5 hover:bg-white/10"
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
              className="rounded-md p-1.5 hover:bg-white/10"
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
