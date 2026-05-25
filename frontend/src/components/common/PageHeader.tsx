import type { ReactNode } from "react";

interface Props {
  title: string;
  // ReactNode rather than `string` so callers can compose rich subtitles
  // (icon + metadata + code spans) — e.g. PaperChatPage showing the active
  // manuscript title plus path. Plain strings keep working because `string`
  // is a valid ReactNode.
  description?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: Props) {
  return (
    <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <div className="mt-1 text-sm text-[var(--color-muted-foreground)]">{description}</div>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
