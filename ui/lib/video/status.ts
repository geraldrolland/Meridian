import type { VideoStatus } from "@/lib/types";

export const STATUS_ORDER: VideoStatus[] = [
  "AWAITING_UPLOAD",
  "QUEUED",
  "PROCESSING",
  "GENERATING_MANIFEST",
  "COMPLETED",
];

export const STATUS_META: Record<
  VideoStatus,
  { label: string; description: string; tone: "info" | "neutral" | "progress" | "success" | "warning" | "danger" }
> = {
  AWAITING_UPLOAD: {
    label: "Uploading",
    description: "Waiting for storage confirmation",
    tone: "info",
  },
  QUEUED: {
    label: "Queued",
    description: "Waiting for the processing pipeline",
    tone: "neutral",
  },
  PROCESSING: {
    label: "Processing",
    description: "Transcoding 360p–1080p renditions",
    tone: "progress",
  },
  GENERATING_MANIFEST: {
    label: "Finalizing",
    description: "Building DASH manifest",
    tone: "progress",
  },
  COMPLETED: {
    label: "Ready",
    description: "Playback available",
    tone: "success",
  },
  FAILED: {
    label: "Failed",
    description: "Processing could not complete",
    tone: "danger",
  },
  RETRY: {
    label: "Needs retry",
    description: "You can requeue this video",
    tone: "warning",
  },
};

export function statusLabel(status: VideoStatus): string {
  return STATUS_META[status]?.label ?? status;
}

export function statusTone(status: VideoStatus): string {
  return STATUS_META[status]?.tone ?? "neutral";
}

export function pipelineStepIndex(status: VideoStatus): number {
  if (status === "FAILED" || status === "RETRY") return -1;
  const i = STATUS_ORDER.indexOf(status);
  return i;
}

export const STEPS = [
  { key: "AWAITING_UPLOAD", title: "Upload received" },
  { key: "QUEUED", title: "Queued" },
  { key: "PROCESSING", title: "Transcode" },
  { key: "GENERATING_MANIFEST", title: "Manifest" },
  { key: "COMPLETED", title: "Ready" },
] as const;
