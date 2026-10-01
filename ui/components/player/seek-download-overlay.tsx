"use client";

import { AnimatePresence, motion } from "framer-motion";

export interface SeekDownloadOverlayProps {
  /** True while a seek is stalled waiting on its target segment. */
  visible: boolean;
  /** Percent (0-100) of the target segment downloaded, or null when Content-Length is unknown. */
  percent: number | null;
}

/**
 * Replaces the frozen frame while a seek waits for its segment: shows how much of the
 * particular segment has arrived. Falls back to an indeterminate shimmer when the server
 * sends no Content-Length, so a missing byte total never becomes a lying 0%.
 */
export function SeekDownloadOverlay({ visible, percent }: SeekDownloadOverlayProps) {
  const determinate = typeof percent === "number" && Number.isFinite(percent);
  const value = determinate ? Math.min(100, Math.max(0, Math.round(percent))) : 0;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.1 }}
          role="status"
          data-testid="seek-download-overlay"
          className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-black/50"
        >
          <p className="text-sm font-medium text-zinc-200">Downloading</p>

          <div
            className="h-2 w-48 overflow-hidden rounded-full bg-zinc-800"
            role="progressbar"
            aria-label="Segment download progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={determinate ? value : undefined}
            aria-valuetext={determinate ? `${value}%` : "Downloading"}
          >
            {determinate ? (
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                initial={{ width: 0 }}
                animate={{ width: `${value}%` }}
                transition={{ duration: 0.15, ease: "easeOut" }}
              />
            ) : (
              <motion.div
                className="h-full w-1/3 rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                initial={{ x: "-120%" }}
                animate={{ x: "320%" }}
                transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
              />
            )}
          </div>

          {/* Hidden from assistive tech: the progressbar already carries aria-valuenow, and
              announcing every tick would spam a screen reader. */}
          <span
            aria-hidden="true"
            className={determinate ? "font-mono text-xs text-zinc-400" : "sr-only"}
          >
            {determinate ? `${value}%` : "Downloading"}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
