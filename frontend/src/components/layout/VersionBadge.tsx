import { GitBranch } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { BuildInfo } from "@/types/api";

interface Props {
  build: BuildInfo;
  className?: string;
}

/**
 * Identity stamp for the running backend.
 *
 * Renders the short git SHA + dirty marker. On hover the title attribute
 * carries the full SHA, commit subject, and commit timestamp so power
 * users can copy-paste straight into `git show <sha>` without losing
 * info to truncation.
 *
 * Why surface this at all? Because the most common "I just fixed this
 * bug and it's still happening" report turns out to be a stale backend
 * still listening on the port. Making the version *visible* without a
 * shell removes that whole class of false reports.
 */
export function VersionBadge({ build, className }: Props) {
  const { t } = useTranslation();
  const isUnknown = build.git_sha === "unknown";
  const shortSha = isUnknown ? t("app.unknown") : build.git_sha_short;
  const title = isUnknown
    ? t("app.buildUnknownTooltip")
    : [
        `${t("app.buildShaLabel")}: ${build.git_sha}`,
        build.commit_subject ? `${t("app.buildSubjectLabel")}: ${build.commit_subject}` : null,
        build.commit_ts ? `${t("app.buildAtLabel")}: ${build.commit_ts}` : null,
        build.git_dirty ? t("app.buildDirtyTooltip") : null,
      ]
        .filter((s): s is string => Boolean(s))
        .join("\n");

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-[var(--color-border)]",
        "px-1.5 py-0.5 font-mono text-[10px]",
        build.git_dirty
          ? // Amber tint when the running process is on a dirty tree —
            // typically a dev session, but worth flagging unmistakably.
            "border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
          : "bg-[var(--color-card)] text-[var(--color-muted-foreground)]",
        className,
      )}
      title={title}
      aria-label={`${t("app.buildShaLabel")}: ${build.git_sha_short}${build.git_dirty ? " (dirty)" : ""}`}
    >
      <GitBranch className="h-3 w-3 shrink-0" aria-hidden />
      {shortSha}
      {build.git_dirty ? <span aria-hidden>•</span> : null}
    </span>
  );
}
