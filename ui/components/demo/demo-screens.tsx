"use client";

import { motion } from "framer-motion";
import {
  ArrowLeft,
  ChevronRight,
  Film,
  Loader2,
  LogOut,
  Maximize,
  Pause,
  Play,
  Plus,
  RefreshCw,
  SkipBack,
  SkipForward,
  Upload,
  UploadCloud,
  Video as VideoIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PipelineStepper } from "@/components/video/pipeline-stepper";
import { StatusChip } from "@/components/video/status-chip";
import { cn, formatBytes, formatTime } from "@/lib/utils";
import { STATUS_META, pipelineStepIndex } from "@/lib/video/status";
import type { VideoStatus } from "@/lib/types";
import { useDemoClock, type DemoStep, type DemoView } from "./demo-timeline";

const EMAIL = "jane@studio.co";
const PASSWORD = "meridian";
const FILE_NAME = "master-footage.mp4";
const FILE_SIZE = 248.6 * 1024 * 1024;
const FILE_TYPE = "video/mp4";
const VIDEO_DURATION = 42;

/** Beat-4: cursor clicks "Start upload" at 1100ms, progress runs 2000ms. */
const UPLOAD_CLICK_MS = 1100;
const UPLOAD_PROGRESS_MS = 2000;
/** Beat-3: cursor clicks the dropzone at 1700ms. */
const PICK_CLICK_MS = 1700;
/** Beat-7: cursor clicks play at 1300ms. */
const PLAY_CLICK_MS = 1300;
/** Beat-6: pipeline status timeline (ms since the pipeline step started). */
const PIPELINE_MILESTONES: [number, VideoStatus][] = [
  [4600, "COMPLETED"],
  [2800, "GENERATING_MANIFEST"],
  [800, "PROCESSING"],
  [0, "QUEUED"],
];

export interface DemoScreenProps {
  step: DemoStep;
  running: boolean;
  staticMode: boolean;
}

export function DemoScreen({ step, running, staticMode }: DemoScreenProps) {
  switch (step.view as DemoView) {
    case "login":
      return <LoginScreen step={step} running={running} staticMode={staticMode} />;
    case "dash-empty":
      return <DashboardEmptyScreen />;
    case "upload-pick":
    case "upload-run":
      return <UploadScreen step={step} running={running} staticMode={staticMode} />;
    case "dash-grid":
      return <DashboardGridScreen />;
    case "detail":
    default:
      return <DetailScreen step={step} running={running} staticMode={staticMode} />;
  }
}

/* ------------------------------------------------------------------ */
/* App shell chrome                                                    */
/* ------------------------------------------------------------------ */

function AppHeader({ section }: { section: "library" | "upload" }) {
  const items = [
    { id: "library", label: "Library", icon: VideoIcon },
    { id: "upload", label: "Upload", icon: Upload },
  ] as const;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/80 px-8">
      <div className="flex items-center gap-8">
        <Logo className="text-base" />
        <nav className="flex items-center gap-1">
          {items.map((item) => {
            const active = section === item.id;
            return (
              <span
                key={item.id}
                className={cn(
                  "relative rounded-lg px-3 py-1.5 text-sm font-medium",
                  active ? "text-zinc-50" : "text-zinc-400",
                )}
              >
                {active && <span className="absolute inset-0 rounded-lg bg-zinc-800" />}
                <span className="relative z-10 inline-flex items-center gap-1.5">
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </span>
              </span>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <span className="max-w-[180px] truncate text-sm text-zinc-400">{EMAIL}</span>
        <span className="inline-flex h-8 items-center gap-2 rounded-lg px-3 text-xs font-medium text-zinc-200">
          <LogOut className="h-4 w-4" />
          Log out
        </span>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* 1 — Login                                                           */
/* ------------------------------------------------------------------ */

function LoginScreen({ step, running, staticMode }: DemoScreenProps) {
  const t = useDemoClock(running, step.id, staticMode);

  const emailChars = Math.min(EMAIL.length, Math.max(0, Math.floor((t - 250) / 45)));
  const passChars = Math.min(PASSWORD.length, Math.max(0, Math.floor((t - 1150) / 60)));
  const busy = !staticMode && t >= step.clickAt!;

  return (
    <div className="flex h-full items-center justify-center bg-zinc-950 bg-grid bg-glow-brand px-6">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex justify-center">
          <Logo className="text-base" />
        </div>
        <Card>
          <CardHeader className="space-y-1 p-5 pb-3">
            <CardTitle className="text-xl">Sign in</CardTitle>
            <p className="text-sm text-zinc-400">Access your MERIDIAN library and uploads</p>
          </CardHeader>
          <CardContent className="space-y-3.5 p-5 pt-0">
            <div className="space-y-1.5">
              <Label className="text-xs">Email</Label>
              <Input readOnly value={emailChars ? EMAIL.slice(0, emailChars) : ""} placeholder="jane@studio.co" className="h-9" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Password</Label>
              <Input readOnly type="password" value={"x".repeat(passChars)} placeholder="••••••••" className="h-9" />
            </div>
            <div className="pt-1">
              <Button data-target="signin" className="w-full" disabled={busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </div>
            <p className="text-center text-xs text-zinc-400">
              No account? <span className="font-medium text-brand-400">Create account</span>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 2 — Library, empty state                                            */
/* ------------------------------------------------------------------ */

function DashboardEmptyScreen() {
  return (
    <div className="flex h-full flex-col bg-zinc-950">
      <AppHeader section="library" />
      <div className="flex-1 px-8 py-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Library</h1>
            <p className="mt-1 text-sm text-zinc-400">Videos tracked on this device</p>
          </div>
          <div className="flex gap-2">
            <span className="inline-flex h-8 items-center gap-2 rounded-lg border border-zinc-700 px-3 text-xs font-medium text-zinc-100">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </span>
            <span className="inline-flex h-8 items-center gap-2 rounded-lg bg-brand-500 px-3 text-xs font-medium text-white">
              <Plus className="h-4 w-4" />
              Upload
            </span>
          </div>
        </div>

        <div className="mt-5 flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-700 bg-zinc-900/30 px-6 py-12 text-center">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-brand-500/10 text-brand-400">
            <Film className="h-7 w-7" />
          </span>
          <h2 className="font-display text-xl font-semibold">No videos yet</h2>
          <p className="mt-2 max-w-sm text-sm text-zinc-400">
            Upload your first master file to see pipeline status and adaptive playback here.
          </p>
          <span className="mt-6">
            <Button data-target="upload-cta">
              <Plus className="h-4 w-4" />
              Upload video
            </Button>
          </span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 3 + 4 — Upload screen                                               */
/* ------------------------------------------------------------------ */

function UploadScreen({ step, running, staticMode }: DemoScreenProps) {
  const t = useDemoClock(running, step.id, staticMode);
  const picking = step.view === "upload-pick";

  const picked = !picking || t >= PICK_CLICK_MS;
  const busy = !picking && t >= UPLOAD_CLICK_MS;
  const pct = picking
    ? 0
    : Math.min(100, Math.max(0, ((t - UPLOAD_CLICK_MS) / UPLOAD_PROGRESS_MS) * 100));

  const stageIndex = pct <= 0 ? -1 : pct < 6 ? 0 : pct < 94 ? 1 : 2;
  const stages = ["PREPARING", "UPLOADING", "FINALIZING"] as const;
  const message =
    stageIndex === 0
      ? "Preparing upload…"
      : stageIndex === 1
        ? `Uploading to storage · ${formatBytes((pct / 100) * FILE_SIZE)} of ${formatBytes(FILE_SIZE)}`
        : stageIndex === 2
          ? "Finalizing upload…"
          : "";

  return (
    <div className="flex h-full flex-col bg-zinc-950">
      <AppHeader section="upload" />
      <div className="mx-auto w-full max-w-[640px] flex-1 px-8 py-5">
        <div className="mb-4">
          <h1 className="font-display text-3xl font-bold leading-tight tracking-tight">
            Upload video
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Files upload directly to storage, then the pipeline takes over.
          </p>
        </div>

        <Card>
          <CardContent className="space-y-4 p-5 pt-5">
            {/* Dropzone replica */}
            <div
              data-target="dropzone"
              className="flex w-full flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-zinc-700 bg-zinc-900/40 px-6 py-8 text-center"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-brand-500/10 text-brand-400">
                <UploadCloud className="h-6 w-6" />
              </span>
              <span className="font-display text-base font-semibold text-zinc-100">
                {picked ? FILE_NAME : "Drop a video here, or browse"}
              </span>
              <span className="text-xs text-zinc-500">
                {picked ? "Click or drop to replace" : "mp4 · mov · avi · mkv · webm · flv · wmv"}
              </span>
            </div>

            {picked && (
              <motion.div
                initial={staticMode ? false : { opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                className="flex items-center justify-between gap-3 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-100">{FILE_NAME}</p>
                  <p className="font-mono text-xs text-zinc-500">
                    {formatBytes(FILE_SIZE)} · {FILE_TYPE}
                  </p>
                </div>
              </motion.div>
            )}

            {busy && (
              <div className="space-y-3">
                <ol className="flex flex-wrap items-center gap-2" aria-hidden>
                  {stages.map((stage, i) => (
                    <li key={stage} className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-[11px] font-semibold uppercase tracking-[0.08em]",
                          i === stageIndex
                            ? "text-brand-400"
                            : i < stageIndex
                              ? "text-emerald-400"
                              : "text-zinc-500",
                        )}
                      >
                        {stage}
                      </span>
                      {i < stages.length - 1 && <ChevronRight className="h-3 w-3 text-zinc-700" />}
                    </li>
                  ))}
                </ol>

                <div className="space-y-2">
                  <div className="flex justify-between gap-2 text-xs text-zinc-400">
                    <span className="truncate">{message}</span>
                    <span className="font-mono">{Math.round(pct)}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ ease: "easeOut", duration: 0.15 }}
                    />
                  </div>
                </div>
              </div>
            )}

            {busy ? (
              <span className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-zinc-700 bg-transparent text-sm font-medium text-zinc-100">
                Cancel
              </span>
            ) : (
              <Button data-target="start-upload" size="lg" className="w-full">
                Start upload
              </Button>
            )}

            <p className="text-center text-xs text-zinc-500">Processing starts automatically</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 5 — Library with the new video                                      */
/* ------------------------------------------------------------------ */

function VideoCardMock() {
  return (
    <div
      data-target="video-card"
      className="block overflow-hidden rounded-xl border border-brand-500/40 bg-zinc-900/60 shadow-[0_0_40px_-12px_rgba(51,88,255,0.35)]"
    >
      <div className="relative aspect-video overflow-hidden bg-zinc-950">
        <div className="flex h-full items-center justify-center bg-gradient-to-br from-zinc-900 via-zinc-950 to-zinc-900">
          <Film className="h-10 w-10 text-zinc-700" />
        </div>
        <div className="absolute left-3 top-3">
          <StatusChip status="AWAITING_UPLOAD" />
        </div>
        <div className="absolute inset-0 flex items-center justify-center bg-black/30">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-500 text-white shadow-lg">
            <Play className="h-5 w-5 translate-x-0.5" fill="currentColor" />
          </span>
        </div>
      </div>
      <div className="space-y-1 p-4">
        <p className="truncate font-medium text-zinc-100">{FILE_NAME}</p>
        <p className="text-xs text-zinc-500">Just now · 0 retries</p>
      </div>
    </div>
  );
}

function GhostCard() {
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40 opacity-60">
      <div className="flex aspect-video items-center justify-center bg-gradient-to-br from-zinc-900 via-zinc-950 to-zinc-900">
        <Film className="h-9 w-9 text-zinc-800" />
      </div>
      <div className="space-y-2 p-4">
        <div className="h-3.5 w-2/3 rounded bg-zinc-800" />
        <div className="h-3 w-1/3 rounded bg-zinc-800/70" />
      </div>
    </div>
  );
}

function DashboardGridScreen() {
  return (
    <div className="flex h-full flex-col bg-zinc-950">
      <AppHeader section="library" />
      <div className="flex-1 px-8 py-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Library</h1>
            <p className="mt-1 text-sm text-zinc-400">Videos tracked on this device</p>
            <div className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
              <span>Live updates on</span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Live
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <span className="inline-flex h-8 items-center gap-2 rounded-lg border border-zinc-700 px-3 text-xs font-medium text-zinc-100">
              <RefreshCw className="h-4 w-4" />
              Refresh
            </span>
            <span className="inline-flex h-8 items-center gap-2 rounded-lg bg-brand-500 px-3 text-xs font-medium text-white">
              <Plus className="h-4 w-4" />
              Upload
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <VideoCardMock />
          <GhostCard />
          <GhostCard />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 6 + 7 — Video detail: pipeline transitions, then playback           */
/* ------------------------------------------------------------------ */

function DemoPlayer({ playing, playT, staticMode }: { playing: boolean; playT: number; staticMode: boolean }) {
  const current = Math.min(VIDEO_DURATION, playT / 1000);
  const pct = (current / VIDEO_DURATION) * 100;

  return (
    <div className="relative h-[240px] overflow-hidden rounded-xl border border-zinc-800 bg-black">
      <div className="absolute inset-0 bg-gradient-to-br from-zinc-900 via-zinc-950 to-zinc-900" />
      <div className="absolute inset-0 bg-grid opacity-40" />
      {playing && (
        <>
          <motion.div
            aria-hidden
            className="absolute -left-16 top-0 h-44 w-72 rounded-full bg-brand-500/30 blur-3xl"
            animate={{ x: [0, 70, 0], y: [0, -26, 0] }}
            transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
          />
          <motion.div
            aria-hidden
            className="absolute -right-10 bottom-0 h-44 w-72 rounded-full bg-emerald-500/20 blur-3xl"
            animate={{ x: [0, -55, 0], y: [0, 22, 0] }}
            transition={{ duration: 11, repeat: Infinity, ease: "easeInOut" }}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="font-display text-2xl font-bold tracking-[0.3em] text-white/10">
              MERIDIAN
            </span>
          </div>
        </>
      )}

      {!playing && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/30">
          <span
            data-target="play"
            className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-500 text-white shadow-[0_0_40px_-8px_rgba(51,88,255,0.8)]"
          >
            <Play className="h-7 w-7 translate-x-0.5" fill="currentColor" />
          </span>
        </div>
      )}

      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black via-black/80 to-transparent px-3 pb-3 pt-8">
        <div className="relative mb-2 h-1.5 rounded-full bg-white/15">
          <motion.div
            className="absolute inset-y-0 left-0 rounded-full bg-brand-500"
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.12, ease: "linear" }}
          />
          <span
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow"
            style={{ left: `${pct}%` }}
          />
        </div>
        <div className="flex items-center gap-2 text-white">
          <span className="rounded-lg p-1.5">
            {playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
          </span>
          <span className="rounded-lg p-1.5">
            <SkipBack className="h-4 w-4" />
          </span>
          <span className="rounded-lg p-1.5">
            <SkipForward className="h-4 w-4" />
          </span>
          <span className="ml-1 font-mono text-[11px] text-zinc-300">
            {staticMode ? formatTime(0) : formatTime(current)} / {formatTime(VIDEO_DURATION)}
          </span>
          <span className="ml-auto inline-flex items-center rounded-md border border-white/15 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-zinc-300">
            1080p · DASH
          </span>
          <span className="rounded-lg p-1.5">
            <Maximize className="h-4 w-4" />
          </span>
        </div>
      </div>
    </div>
  );
}

function DetailScreen({ step, running, staticMode }: DemoScreenProps) {
  const playingStep = step.id === "play";
  const t = useDemoClock(running, step.id, staticMode);
  const playT = useDemoClock(running && playingStep, "demo-play", staticMode);

  const status: VideoStatus = playingStep
    ? "COMPLETED"
    : (PIPELINE_MILESTONES.find(([at]) => t >= at)?.[1] ?? "QUEUED");
  const meta = STATUS_META[status];
  const stepIndex = pipelineStepIndex(status);

  const [armed, setArmed] = useState(false);
  const playKey = `${playingStep}:${staticMode}`;
  const [prevPlayKey, setPrevPlayKey] = useState(playKey);
  if (prevPlayKey !== playKey) {
    setPrevPlayKey(playKey);
    setArmed(false);
  }
  useEffect(() => {
    if (!playingStep || staticMode) return;
    const timer = setTimeout(() => setArmed(true), PLAY_CLICK_MS);
    return () => clearTimeout(timer);
  }, [playingStep, staticMode]);
  const playing = armed && playingStep && !staticMode;

  return (
    <div className="flex h-full flex-col bg-zinc-950">
      <AppHeader section="library" />
      <div className="flex-1 px-8 py-5">
        <div className="mb-3">
          <span className="inline-flex items-center gap-1 text-sm text-zinc-400">
            <ArrowLeft className="h-4 w-4" />
            Library
          </span>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="font-display text-2xl font-bold tracking-tight">{FILE_NAME}</h1>
            <StatusChip status={status} />
          </div>
          <p className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
            <span>Created Sep 28, 2026, 09:14 AM</span>
            <span>retries 0</span>
            <span className="font-mono text-zinc-600">7f3a91c2-4e88-4b0d-9a15-2c6e8f0b17d4</span>
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0 space-y-3">
            {status === "COMPLETED" ? (
              <motion.div
                key="player"
                initial={staticMode ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
              >
                <DemoPlayer playing={playing} playT={playT} staticMode={staticMode} />
              </motion.div>
            ) : (
              <motion.div
                key="panel"
                initial={staticMode ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
                className="relative overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950"
              >
                <div className="flex h-[240px] flex-col items-center justify-center gap-2 bg-grid px-8 text-center">
                  <p className="font-display text-xl font-semibold text-zinc-200">{meta.label}</p>
                  <p className="max-w-md text-sm leading-relaxed text-zinc-500">
                    {meta.description}
                  </p>
                </div>
              </motion.div>
            )}

            <Card data-target="pipeline-card" className="rounded-xl">
              <CardHeader className="flex-row items-center justify-between space-y-0 p-4 pb-2">
                <CardTitle className="text-base">Pipeline</CardTitle>
                <span className="font-mono text-xs text-zinc-500">
                  Status: {status}
                  {stepIndex >= 0 ? ` · step ${stepIndex + 1} of 5` : ""}
                </span>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                <PipelineStepper status={status} />
              </CardContent>
            </Card>
          </div>

          <aside className="min-w-0 space-y-3">
            <Card>
              <CardHeader className="p-4 pb-2">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                  What&apos;s happening
                </p>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                <p className="text-sm leading-6 text-zinc-300">{meta.description}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-3 p-4 pt-4">
                {[
                  { label: "Renditions", value: "360p → 1080p" },
                  { label: "Segment", value: "6s CMAF" },
                  { label: "Manifest", value: "MPEG-DASH" },
                ].map((m) => (
                  <div key={m.label}>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500">
                      {m.label}
                    </p>
                    <p className="font-display text-base font-semibold text-zinc-100">{m.value}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </div>
  );
}
