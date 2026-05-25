import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const baseField =
  "flex w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-3 py-2 text-sm shadow-sm placeholder:text-[var(--color-muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] disabled:cursor-not-allowed disabled:opacity-50";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input ref={ref} type={type} className={cn(baseField, "h-9", className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(baseField, "min-h-24 resize-y", className)} {...props} />
));
Textarea.displayName = "Textarea";
