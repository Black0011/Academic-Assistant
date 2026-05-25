import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge tailwind classes — last write wins on conflicts. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
