"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

export function Logo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "group inline-flex items-center gap-2 font-display text-lg font-bold tracking-tight text-zinc-50",
        className,
      )}
      aria-label="MERIDIAN home"
    >
      <span className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 text-[13px] font-black text-white shadow-[0_0_20px_-4px_rgba(239,25,42,0.7)]">
        M
        <span className="absolute inset-0 rounded-lg ring-1 ring-inset ring-white/20" />
      </span>
      <span className="tracking-[0.18em]">MERIDIAN</span>
    </Link>
  );
}
