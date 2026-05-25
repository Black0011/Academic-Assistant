import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const badgeStyles = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        neutral: "border-transparent bg-[var(--color-secondary)] text-[var(--color-secondary-foreground)]",
        primary: "border-transparent bg-[var(--color-primary)] text-[var(--color-primary-foreground)]",
        outline: "text-[var(--color-foreground)]",
        success: "border-transparent bg-[var(--color-success)] text-[var(--color-success-foreground)]",
        warning: "border-transparent bg-[var(--color-warning)] text-[var(--color-warning-foreground)]",
        destructive:
          "border-transparent bg-[var(--color-destructive)] text-[var(--color-destructive-foreground)]",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeStyles> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeStyles({ variant }), className)} {...props} />;
}
