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
    label: "UPLOADING",
    description: "Upload received — waiting for storage confirmation",
    tone: "info",
  },
  QUEUED: {
    label: "QUEUED",
    description: "Queued for the processing pipeline",
    tone: "neutral",
  },
  PROCESSING: {
    label: "PROCESSING",
    description:
      "Transcoding 360p to 1080p renditions and generating the thumbnail. You can leave this page — we'll tell you when it's ready.",
    tone: "progress",
  },
  GENERATING_MANIFEST: {
    label: "FINALIZING",
    description: "Building the DASH manifest",
    tone: "progress",
  },
  COMPLETED: {
    label: "READY",
    description: "Playback available",
    tone: "success",
  },
  FAILED: {
    label: "FAILED",
    description: "Processing could not complete",
    tone: "danger",
  },
  RETRY: {
    label: "NEEDS ATTENTION",
    description: "You can requeue this video",
    tone: "warning",
  },
};

export function statusLabel(status: VideoStatus): string {
  return STATUS_META[status]?.label ?? status;
}

/**
 * Statuses where the owner may delete the video — mirrors the service's
 * 409 guard (QUEUED / PROCESSING / GENERATING_MANIFEST are blocked).
 */
export const DELETABLE_STATUSES: VideoStatus[] = [
  "AWAITING_UPLOAD",
  "COMPLETED",
  "FAILED",
  "RETRY",
];

export function canDeleteVideo(status: VideoStatus): boolean {
  return DELETABLE_STATUSES.includes(status);
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
  { key: "QUEUED", title: "Queued for pipeline" },
  { key: "PROCESSING", title: "Transcode & thumbnail" },
  { key: "GENERATING_MANIFEST", title: "DASH manifest" },
  { key: "COMPLETED", title: "Ready to watch" },
] as const;
