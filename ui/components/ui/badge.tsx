import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-brand-500/15 text-brand-400",
        secondary: "border-transparent bg-zinc-800 text-zinc-300",
        success: "border-emerald-500/30 bg-emerald-500/12 text-emerald-400",
        warning: "border-amber-500/30 bg-amber-500/12 text-amber-400",
        danger: "border-red-500/30 bg-red-500/12 text-red-400",
        info: "border-sky-500/30 bg-sky-500/12 text-sky-400",
        progress: "border-blue-500/30 bg-blue-500/12 text-blue-400",
        outline: "border-zinc-700 text-zinc-300",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
