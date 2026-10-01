"use client";

import { cn } from "@/lib/utils";
import type { WsStatus } from "@/lib/realtime/ws";

const PILL_META: Record<WsStatus, { label: string; dot: string; text: string }> = {
  open: { label: "Live", dot: "bg-emerald-500", text: "text-emerald-400" },
  connecting: { label: "Reconnecting", dot: "bg-amber-500", text: "text-amber-400" },
  closed: { label: "Reconnecting", dot: "bg-amber-500", text: "text-amber-400" },
  error: { label: "Offline", dot: "bg-red-500", text: "text-red-400" },
};

export function ConnectionPill({ status, className }: { status: WsStatus; className?: string }) {
  const meta = PILL_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.08em]",
        meta.text,
        className,
      )}
      role="status"
    >
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", meta.dot)} aria-hidden />
      {meta.label}
    </span>
  );
}
