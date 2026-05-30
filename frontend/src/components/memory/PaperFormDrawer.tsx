/**
 * Manual create / edit drawer for a knowledge ``PaperCard`` (P13.C).
 *
 * Distinct from the ingest panel, which extracts metadata from a PDF /
 * markdown blob and also triggers vector + episodic writes. This drawer
 * is for the curated workflow: "I read this paper, I know the fields,
 * I want a card with my own classification."
 *
 * Layout choice: modal panel (``fixed inset-0 / bg-black/40``) instead
 * of an inline expander because the form has many fields (12+) and the
 * surrounding KnowledgeTab is already dense. We follow the same pattern
 * as ``components/settings/OnboardingDialog.tsx`` so users don't see
 * yet-another-modal-style.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import type {
  CreatePaperCardInput,
  PaperCard,
  UpdatePaperCardInput,
} from "@/types/api";

export type PaperFormSubmit =
  | { mode: "create"; payload: CreatePaperCardInput }
  | { mode: "update"; paperId: string; payload: UpdatePaperCardInput };

interface PaperFormDrawerProps {
  /** ``null`` opens the drawer in create-mode; passing a card opens edit. */
  card: PaperCard | null;
  open: boolean;
  onClose: () => void;
  onSubmit: (s: PaperFormSubmit) => void | Promise<void>;
  submitting?: boolean;
}

interface FormState {
  title: string;
  authors: string;
  year: string;
  venue: string;
  url: string;
  field_major: string;
  field_minor: string;
  citation_url: string;
  citation_bibtex: string;
  experiment_results: string;
  tags: string;
  abstract: string;
  summary: string;
  method: string;
  findings: string;
}

function fromCard(card: PaperCard | null): FormState {
  if (!card) {
    return {
      title: "",
      authors: "",
      year: "",
      venue: "",
      url: "",
      field_major: "",
      field_minor: "",
      citation_url: "",
      citation_bibtex: "",
      experiment_results: "",
      tags: "",
      abstract: "",
      summary: "",
      method: "",
      findings: "",
    };
  }
  return {
    title: card.title ?? "",
    authors: (card.authors ?? []).join(", "),
    year: card.year !== null && card.year !== undefined ? String(card.year) : "",
    venue: card.venue ?? "",
    url: card.url ?? "",
    field_major: card.field_major ?? "",
    field_minor: card.field_minor ?? "",
    citation_url: card.citation_url ?? "",
    citation_bibtex: card.citation_bibtex ?? "",
    experiment_results: card.experiment_results ?? "",
    tags: (card.tags ?? []).join(", "),
    abstract: card.abstract ?? "",
    summary: card.summary ?? "",
    method: card.method ?? "",
    findings: card.findings ?? "",
  };
}

function parseCSV(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function PaperFormDrawer({
  card,
  open,
  onClose,
  onSubmit,
  submitting = false,
}: PaperFormDrawerProps) {
  const { t } = useTranslation();
  const isEdit = card !== null;
  const [form, setForm] = useState<FormState>(() => fromCard(card));

  // Reset whenever the drawer (re)opens or the target card changes —
  // a stale "create" form must NOT bleed into an "edit" session.
  useEffect(() => {
    if (open) setForm(fromCard(card));
  }, [open, card]);

  // Close on ESC for parity with OnboardingDialog.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((s) => ({ ...s, [key]: value }));

  const titleOk = form.title.trim().length > 0;
  // Year accepts only 4-digit numerics OR empty; empty maps to null on
  // submit so the backend gets the explicit "no year" signal.
  const yearOk = form.year.trim() === "" || /^\d{4}$/.test(form.year.trim());
  const canSubmit = titleOk && yearOk && !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    // Construct a payload that omits empty strings for the optional
    // ``str | None`` fields. Sending ``""`` to clear is the backend's
    // documented escape hatch; for the *create* path we want to send
    // ``null`` (or omit) so legacy clients reading the YAML get a real
    // missing key, not an empty string.
    const year = form.year.trim() === "" ? null : Number(form.year);
    const base = {
      title: form.title.trim(),
      authors: parseCSV(form.authors),
      year,
      venue: form.venue.trim() || null,
      url: form.url.trim() || null,
      field_major: form.field_major.trim() || null,
      field_minor: form.field_minor.trim() || null,
      citation_url: form.citation_url.trim() || null,
      citation_bibtex: form.citation_bibtex.trim() || null,
      experiment_results: form.experiment_results.trim() || null,
      tags: parseCSV(form.tags),
      abstract: form.abstract,
      summary: form.summary,
      method: form.method,
      findings: form.findings,
    };

    if (isEdit && card) {
      void onSubmit({ mode: "update", paperId: card.paper_id, payload: base });
    } else {
      void onSubmit({ mode: "create", payload: base });
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="paper-form-title"
      onClick={(e) => {
        // Click outside the panel = cancel. Stop-prop on the panel keeps
        // form clicks from bubbling out.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-lg border bg-[var(--color-background)] shadow-xl"
      >
        <div className="sticky top-0 flex items-center justify-between border-b bg-[var(--color-background)] px-5 py-3">
          <h2 id="paper-form-title" className="text-sm font-semibold">
            {isEdit ? t("memory.paperForm.titleEdit") : t("memory.paperForm.titleCreate")}
          </h2>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={onClose}
            aria-label={t("common.close") || "Close"}
            className="h-7 w-7"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <FieldText
            id="pf-title"
            label={t("memory.paperForm.fields.title") + " *"}
            value={form.title}
            onChange={(v) => setField("title", v)}
            required
            error={!titleOk}
          />

          <div className="grid gap-3 sm:grid-cols-3">
            <FieldText
              id="pf-year"
              label={t("memory.paperForm.fields.year")}
              value={form.year}
              onChange={(v) => setField("year", v)}
              placeholder="2026"
              error={!yearOk}
              hint={t("memory.paperForm.yearHint")}
            />
            <FieldText
              id="pf-venue"
              label={t("memory.paperForm.fields.venue")}
              value={form.venue}
              onChange={(v) => setField("venue", v)}
              placeholder="ACL"
            />
            <FieldText
              id="pf-authors"
              label={t("memory.paperForm.fields.authors")}
              value={form.authors}
              onChange={(v) => setField("authors", v)}
              placeholder="Alice, Bob"
              hint={t("memory.paperForm.csvHint")}
            />
          </div>

          <FieldText
            id="pf-url"
            label={t("memory.paperForm.fields.url")}
            value={form.url}
            onChange={(v) => setField("url", v)}
            placeholder="https://arxiv.org/abs/..."
            hint={t("memory.paperForm.urlHint")}
          />

          <FieldText
            id="pf-citation-url"
            label={t("memory.paperForm.fields.citationUrl")}
            value={form.citation_url}
            onChange={(v) => setField("citation_url", v)}
            placeholder="https://scholar.googleusercontent.com/scholar.bib?..."
            hint={t("memory.paperForm.citationUrlHint")}
          />

          <FieldArea
            id="pf-citation-bibtex"
            label={t("memory.paperForm.fields.citationBibtex")}
            value={form.citation_bibtex}
            onChange={(v) => setField("citation_bibtex", v)}
            rows={4}
            hint={t("memory.paperForm.citationBibtexHint")}
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <FieldText
              id="pf-major"
              label={t("memory.paperForm.fields.fieldMajor")}
              value={form.field_major}
              onChange={(v) => setField("field_major", v)}
              placeholder="NLP"
              hint={t("memory.paperForm.fieldMajorHint")}
            />
            <FieldText
              id="pf-minor"
              label={t("memory.paperForm.fields.fieldMinor")}
              value={form.field_minor}
              onChange={(v) => setField("field_minor", v)}
              placeholder="LLM-Agent"
              hint={t("memory.paperForm.fieldMinorHint")}
            />
          </div>

          <FieldText
            id="pf-tags"
            label={t("memory.paperForm.fields.tags")}
            value={form.tags}
            onChange={(v) => setField("tags", v)}
            placeholder="rlhf, survey-2026"
            hint={t("memory.paperForm.csvHint")}
          />

          <FieldArea
            id="pf-abstract"
            label={t("memory.paperForm.fields.abstract")}
            value={form.abstract}
            onChange={(v) => setField("abstract", v)}
            rows={3}
          />
          <FieldArea
            id="pf-summary"
            label={t("memory.paperForm.fields.summary")}
            value={form.summary}
            onChange={(v) => setField("summary", v)}
            rows={3}
            hint={t("memory.paperForm.summaryHint")}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <FieldArea
              id="pf-method"
              label={t("memory.paperForm.fields.method")}
              value={form.method}
              onChange={(v) => setField("method", v)}
              rows={3}
            />
            <FieldArea
              id="pf-findings"
              label={t("memory.paperForm.fields.findings")}
              value={form.findings}
              onChange={(v) => setField("findings", v)}
              rows={3}
            />
          </div>

          <FieldArea
            id="pf-experiment-results"
            label={t("memory.paperForm.fields.experimentResults")}
            value={form.experiment_results}
            onChange={(v) => setField("experiment_results", v)}
            rows={3}
            hint={t("memory.paperForm.experimentResultsHint")}
          />
        </div>

        <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t bg-[var(--color-background)] px-5 py-3">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {submitting
              ? t("memory.paperForm.saving")
              : isEdit
                ? t("memory.paperForm.save")
                : t("memory.paperForm.create")}
          </Button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form-field primitives (local — these aren't reused elsewhere yet).
// ---------------------------------------------------------------------------

interface FieldTextProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  error?: boolean;
}

function FieldText({ id, label, value, onChange, placeholder, hint, required, error }: FieldTextProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className={error ? "text-[var(--color-destructive)]" : undefined}>
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        aria-invalid={error || undefined}
      />
      {hint ? (
        <p className="text-[10px] text-[var(--color-muted-foreground)]">{hint}</p>
      ) : null}
    </div>
  );
}

interface FieldAreaProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  hint?: string;
}

function FieldArea({ id, label, value, onChange, rows = 3, hint }: FieldAreaProps) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        className="text-sm"
      />
      {hint ? (
        <p className="text-[10px] text-[var(--color-muted-foreground)]">{hint}</p>
      ) : null}
    </div>
  );
}
