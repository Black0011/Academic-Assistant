/**
 * FilePreviewPanel — collapsible file content viewer above the chat.
 *
 * Modes:
 * - preview: read-only Monaco view of the selected file
 * - edit: editable Monaco with Ctrl+S save
 * - diff: DiffEditor showing before/after revision changes
 *
 * The panel can be resized by dragging a horizontal divider.
 */
import { loader, DiffEditor } from "@monaco-editor/react";
import Editor from "@monaco-editor/react";
loader.config({ paths: { vs: "/monaco-vs" } });
import {
  Check,
  ChevronDown,
  FileText,
  Pencil,
  RotateCcw,
  X,
} from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/Button";
import { useUiStore } from "@/stores/uiStore";

export type PanelMode = "preview" | "edit" | "diff";

interface FilePreviewPanelProps {
  filename: string;
  content: string;
  /** Diff mode: show before (left) and after (right) */
  beforeContent?: string;
  mode: PanelMode;
  onModeChange?: (mode: PanelMode) => void;
  onSave?: (content: string) => void;
  onAcceptDiff?: () => void;
  onRejectDiff?: () => void;
  onCollapse?: () => void;
  /** Revision change banner props */
  revisionLabel?: string;
  onViewDiff?: () => void;
  onKeepChanges?: () => void;
  onRevertChanges?: () => void;
}

export function FilePreviewPanel({
  filename,
  content,
  beforeContent,
  mode,
  onModeChange,
  onSave,
  onAcceptDiff,
  onRejectDiff,
  onCollapse,
  revisionLabel,
  onViewDiff,
  onKeepChanges,
  onRevertChanges,
}: FilePreviewPanelProps) {
  const theme = useUiStore((s) => s.theme);
  const monacoTheme = theme === "dark" ? "vs-dark" : "vs";
  const [draft, setDraft] = useState(content);

  const handleSave = useCallback(() => {
    onSave?.(draft);
  }, [draft, onSave]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (mode === "edit") handleSave();
      }
    },
    [mode, handleSave],
  );

  return (
    <div className="flex flex-col h-full" onKeyDown={handleKeyDown}>
      {/* Header bar */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b bg-[var(--color-card)]/50 px-2">
        <div className="flex items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
          <FileText className="h-3.5 w-3.5" />
          <span className="font-medium truncate max-w-[200px]">{filename}</span>
          <span className="text-[10px] opacity-60">
            {mode === "edit" ? "(editing)" : mode === "diff" ? "(diff)" : "(read-only)"}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {mode === "diff" ? (
            <>
              <Button variant="ghost" size="icon" className="h-5 w-5" onClick={onAcceptDiff} title="Accept changes">
                <Check className="h-3 w-3 text-green-500" />
              </Button>
              <Button variant="ghost" size="icon" className="h-5 w-5" onClick={onRejectDiff} title="Reject changes">
                <X className="h-3 w-3 text-red-500" />
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={() => onModeChange?.(mode === "edit" ? "preview" : "edit")}
              title={mode === "edit" ? "Switch to preview" : "Edit file"}
            >
              <Pencil className="h-3 w-3" />
            </Button>
          )}
          {mode === "edit" && (
            <Button variant="ghost" size="icon" className="h-5 w-5" onClick={handleSave} title="Save (Ctrl+S)">
              <Check className="h-3 w-3" />
            </Button>
          )}
          {onCollapse && (
            <Button variant="ghost" size="icon" className="h-5 w-5" onClick={onCollapse} title="Collapse panel">
              <ChevronDown className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>

      {/* Revision change banner */}
      {revisionLabel && (
        <div className="flex items-center gap-2 border-b bg-amber-500/10 px-3 py-1.5 text-[11px]">
          <span className="text-amber-600 dark:text-amber-400">{revisionLabel}</span>
          <div className="flex gap-1 ml-auto">
            {onViewDiff && (
              <Button variant="outline" size="sm" className="h-5 text-[10px] px-2" onClick={onViewDiff}>View diff</Button>
            )}
            {onKeepChanges && (
              <Button variant="outline" size="sm" className="h-5 text-[10px] px-2" onClick={onKeepChanges}>Keep</Button>
            )}
            {onRevertChanges && (
              <Button variant="outline" size="sm" className="h-5 text-[10px] px-2" onClick={onRevertChanges}>
                <RotateCcw className="h-3 w-3 mr-0.5" /> Revert
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Editor area */}
      <div className="flex-1 min-h-0">
        {mode === "diff" && beforeContent ? (
          <DiffEditor
            height="100%"
            language="latex"
            theme={monacoTheme}
            original={beforeContent}
            modified={content}
            options={{ readOnly: true, minimap: { enabled: false }, fontSize: 12 }}
          />
        ) : (
          <Editor
            height="100%"
            language="latex"
            theme={monacoTheme}
            value={mode === "edit" ? draft : content}
            onChange={(v) => mode === "edit" && setDraft(v ?? "")}
            options={{
              readOnly: mode !== "edit",
              minimap: { enabled: false },
              fontSize: 12,
              lineNumbers: "on",
              wordWrap: "on",
            }}
          />
        )}
      </div>
    </div>
  );
}
