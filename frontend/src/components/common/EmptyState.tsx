import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-10 text-center">
      {Icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-muted)] text-[var(--color-muted-foreground)]">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      )}
      <div className="text-sm font-medium">{title}</div>
      {description && (
        <p className="max-w-sm text-xs text-[var(--color-muted-foreground)]">{description}</p>
      )}
      {action}
    </div>
  );
}
