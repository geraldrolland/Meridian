"use client";

import { motion } from "framer-motion";
import { Check, Loader2, XCircle } from "lucide-react";
import type { VideoStatus } from "@/lib/types";
import { STEPS, pipelineStepIndex } from "@/lib/video/status";
import { cn } from "@/lib/utils";

export function PipelineStepper({ status }: { status: VideoStatus }) {
  const stepIndex = pipelineStepIndex(status);
  const isFail = status === "FAILED";
  const isRetry = status === "RETRY";

  return (
    <ol className="flex flex-col gap-0 sm:flex-row sm:gap-0" aria-current="step">
      {STEPS.map((step, i) => {
        const done = stepIndex > i || status === "COMPLETED";
        const active = stepIndex === i && !isFail && !isRetry;
        const failedHere = (isFail || isRetry) && i === Math.max(stepIndex, 1);

        return (
          <li key={step.key} className="relative flex-1">
            <div className="flex items-start gap-3 sm:block">
              <div className="relative flex flex-col items-center sm:w-full">
                <div className="relative z-10">
                  <motion.div
                    initial={false}
                    animate={{
                      scale: active ? [1, 1.08, 1] : 1,
                    }}
                    transition={{ duration: 0.8, repeat: active ? Infinity : 0, ease: "easeInOut" }}
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-full border text-xs font-semibold",
                      done && "border-emerald-500/50 bg-emerald-500/15 text-emerald-400",
                      active && "border-brand-500/60 bg-brand-500/15 text-brand-400 shadow-[0_0_20px_-4px_rgba(239,25,42,0.6)]",
                      failedHere && "border-red-500/50 bg-red-500/15 text-red-400",
                      !done && !active && !failedHere && "border-zinc-700 bg-zinc-900 text-zinc-500",
                    )}
                  >
                    {done ? (
                      <Check className="h-4 w-4" />
                    ) : active ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : failedHere ? (
                      <XCircle className="h-4 w-4" />
                    ) : (
                      i + 1
                    )}
                  </motion.div>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={cn(
                      "hidden h-0.5 w-full sm:mt-3 sm:block",
                      done ? "bg-emerald-500/40" : "bg-zinc-800",
                    )}
                  />
                )}
              </div>
              <div className="pb-5 sm:mt-3 sm:pb-0 sm:text-center">
                <p
                  className={cn(
                    "text-sm font-medium",
                    done && "text-emerald-400",
                    active && "text-brand-400",
                    failedHere && "text-red-400",
                    !done && !active && !failedHere && "text-zinc-500",
                  )}
                >
                  {step.title}
                </p>
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <div className="absolute left-4 top-9 h-full w-0.5 bg-zinc-800 sm:hidden" aria-hidden />
            )}
          </li>
        );
      })}
    </ol>
  );
}
