"use client";

import { Badge } from "@/components/ui/badge";
import type { VideoStatus } from "@/lib/types";
import { STATUS_META } from "@/lib/video/status";
import { cn } from "@/lib/utils";

const variantMap = {
  info: "info",
  neutral: "secondary",
  progress: "progress",
  success: "success",
  warning: "warning",
  danger: "danger",
} as const;

export function StatusChip({ status, className }: { status: VideoStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <Badge variant={variantMap[meta.tone]} className={cn("gap-1.5", className)}>
      {(status === "PROCESSING" || status === "GENERATING_MANIFEST" || status === "QUEUED" || status === "AWAITING_UPLOAD") && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {meta.label}
    </Badge>
  );
}
