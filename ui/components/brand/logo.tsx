"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

function MeridianSymbol({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {/* A — Ring: the lens, a frame that holds every video */}
      <circle cx="16" cy="16" r="13" />
      {/* B — Meridian arcs: global, distributed, always in reach */}
      <ellipse cx="16" cy="16" rx="6.5" ry="13" />
      {/* C — Playhead: the moment a video becomes playable */}
      <path d="M13.5 11.5 L21 16 L13.5 20.5 Z" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function Logo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "group inline-flex items-center gap-2 font-display text-lg font-bold text-zinc-50",
        className,
      )}
      aria-label="MERIDIAN home"
    >
      <MeridianSymbol className="h-7 w-7 shrink-0 transition-colors group-hover:text-brand-400" />
      <span className="tracking-[0.14em]">MERIDIAN</span>
    </Link>
  );
}
