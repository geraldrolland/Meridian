import { useEffect, useState } from "react";

export type DemoView =
  | "login"
  | "dash-empty"
  | "upload-pick"
  | "upload-run"
  | "dash-grid"
  | "detail";

export type DemoStepId =
  | "signin"
  | "open-upload"
  | "pick-file"
  | "start-upload"
  | "open-video"
  | "pipeline"
  | "play";

export interface DemoStep {
  id: DemoStepId;
  view: DemoView;
  label: string;
  caption: string;
  /** Value of `data-target` on the element the virtual cursor points at. */
  target: string;
  /** Offset into the step (ms) when the cursor clicks. Omit for hover-only steps. */
  clickAt?: number;
  /** Total length of the step (ms). */
  duration: number;
}

export const DEMO_TICK_MS = 50;

/** Clock value returned in reduced-motion mode so every screen renders its settled state. */
export const DEMO_STATIC_ELAPSED = 60_000;

export const DEMO_STEPS: DemoStep[] = [
  {
    id: "signin",
    view: "login",
    label: "Sign in",
    caption: "Authenticate with email and password",
    target: "signin",
    clickAt: 2500,
    duration: 3600,
  },
  {
    id: "open-upload",
    view: "dash-empty",
    label: "Open upload",
    caption: "Jump into the upload workspace from the library",
    target: "upload-cta",
    clickAt: 1500,
    duration: 2200,
  },
  {
    id: "pick-file",
    view: "upload-pick",
    label: "Select file",
    caption: "Drop or browse a master file",
    target: "dropzone",
    clickAt: 1700,
    duration: 2600,
  },
  {
    id: "start-upload",
    view: "upload-run",
    label: "Upload",
    caption: "Direct-to-storage with live progress",
    target: "start-upload",
    clickAt: 1100,
    duration: 3400,
  },
  {
    id: "open-video",
    view: "dash-grid",
    label: "Open video",
    caption: "Track the new video from your library",
    target: "video-card",
    clickAt: 1600,
    duration: 2400,
  },
  {
    id: "pipeline",
    view: "detail",
    label: "Pipeline",
    caption: "Status streams live over WebSocket until it is ready",
    target: "pipeline-card",
    duration: 5800,
  },
  {
    id: "play",
    view: "detail",
    label: "Play",
    caption: "Adaptive DASH playback from 360p to 1080p",
    target: "play",
    clickAt: 1300,
    duration: 4400,
  },
];

export const DEMO_TOTAL_MS = DEMO_STEPS.reduce((sum, s) => sum + s.duration, 0);

/**
 * Milliseconds elapsed since `resetKey` changed, ticking only while `running`
 * is true so the whole demo (and every screen clock) freezes on pause or
 * when scrolled off screen.
 */
export function useDemoClock(running: boolean, resetKey: string, instant = false): number {
  const [elapsed, setElapsed] = useState(0);
  const [prevResetKey, setPrevResetKey] = useState(resetKey);

  if (prevResetKey !== resetKey) {
    setPrevResetKey(resetKey);
    setElapsed(0);
  }

  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => setElapsed((v) => v + 60), 60);
    return () => clearInterval(iv);
  }, [running]);

  return instant ? DEMO_STATIC_ELAPSED : elapsed;
}
