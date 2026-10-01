"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  formatBitrate,
  reasonLabel,
  type AbrMode,
  type StreamRendition,
} from "@/lib/video/rendition";
import { cn } from "@/lib/utils";

const MODE_VARIANT: Record<AbrMode, "default" | "warning" | "secondary"> = {
  auto: "default",
  fallback: "warning",
  manual: "secondary",
};

const MODE_LABEL: Record<AbrMode, string> = {
  auto: "Auto · server ABR",
  fallback: "Auto · client fallback",
  manual: "Manual",
};

export function RenditionStrip({ state }: { state: StreamRendition | null }) {
  const ladder = state?.ladder ?? [];
  const rendition = state?.rendition ?? null;
  const recommendation = state?.recommendation ?? null;
  const mode = state ? MODE_VARIANT[state.mode] : null;

  const next = recommendation?.recommended;
  const holding = next === undefined || next === rendition || state?.mode === "manual";

  const abrLine = !state
    ? "Waiting for the first segment…"
    : state.mode === "manual"
      ? "Server recommendations paused while a manual rendition is selected"
      : holding
        ? `Holding at ${rendition ?? "—"}`
        : `Next: ${next} · ${reasonLabel(recommendation?.reason)}`;

  const metrics = [
    { label: "Segment", value: state?.segmentIndex != null ? `#${state.segmentIndex}` : "—" },
    { label: "Bandwidth", value: formatBitrate(state?.bandwidthBps ?? null) },
    { label: "Download", value: state?.downloadMs != null ? `${state.downloadMs} ms` : "—" },
    { label: "Buffer", value: state?.bufferSec != null ? `${state.bufferSec.toFixed(1)} s` : "—" },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base">Stream</CardTitle>
        {state && mode ? (
          <Badge variant={mode}>{MODE_LABEL[state.mode]}</Badge>
        ) : (
          <span className="font-mono text-xs text-zinc-500">idle</span>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
            Current rendition
          </p>
          <p
            aria-live="polite"
            className="font-display text-2xl font-semibold leading-8 tracking-tight text-zinc-100"
          >
            {rendition ?? "—"}
          </p>
          {ladder.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {ladder.map((level) => {
                const isActive = level.label === rendition;
                const isNext = !holding && level.label === next;
                return (
                  <li key={level.id}>
                    <span
                      aria-current={isActive ? "true" : undefined}
                      className={cn(
                        "inline-block rounded-md border px-2 py-1 font-mono text-[11px] font-semibold transition-colors",
                        isActive &&
                          "border-brand-500/60 bg-brand-500/15 text-brand-400",
                        !isActive &&
                          isNext &&
                          "border-amber-500/40 bg-amber-500/10 text-amber-400",
                        !isActive &&
                          !isNext &&
                          "border-zinc-800 bg-zinc-900/60 text-zinc-500",
                      )}
                    >
                      {level.label}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="min-w-0 flex-1 border-t border-zinc-800 pt-4 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
            Adaptive bitrate
          </p>
          <p className="mt-1.5 text-sm leading-6 text-zinc-300" title={recommendation?.reason}>
            {abrLine}
          </p>
        </div>

        <dl className="grid shrink-0 grid-cols-2 gap-x-6 gap-y-3 border-t border-zinc-800 pt-4 sm:border-t-0 sm:pt-0">
          {metrics.map((metric) => (
            <div key={metric.label}>
              <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                {metric.label}
              </dt>
              <dd className="font-mono text-sm text-zinc-200">{metric.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
