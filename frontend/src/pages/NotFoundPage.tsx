import { useTranslation } from "react-i18next";

import { LinkButton } from "@/components/ui/LinkButton";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="font-mono text-5xl font-bold tabular-nums">404</div>
      <h2 className="text-lg font-semibold">{t("notFound.title")}</h2>
      <p className="max-w-md text-sm text-[var(--color-muted-foreground)]">
        {t("notFound.description")}
      </p>
      <LinkButton to="/" variant="outline">
        {t("notFound.backHome")}
      </LinkButton>
    </div>
  );
}
