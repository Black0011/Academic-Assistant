# Research Log — Self-Evolution Events

## 2026-05-16 — P14: Citation Audit Soft-Fail + Multi-File Batch Review

### Trigger
Task `#98bc913e7c96` failed with `ValueError: citation audit failed at consult:original: missing bibtex key` for 13 papers. The user also requested multi-file batch review and an outer engineering framework.

### Diagnosis
- `citation_guard.py:audit_citations()` treated missing paper cards as hard failure, blocking entire consult/revision/write workflows
- `_research_missing()` only searched arXiv with raw key, failing for non-arXiv papers
- No mechanism to select multiple bundle files for cross-file review
- `.cursor/` engineering rules were hidden inside the repo, inaccessible to outer agents

### Changes

1. **citation_guard.py (P14.1)**
   - `CitationAuditResult` gains `suspect_citations: list[dict]` field
   - `audit_citations()` collects suspect citations instead of raising `ValueError`
   - `_research_missing()` enhanced: tries multiple query variants + Semantic Scholar fallback
   - New helpers: `_strip_year_prefix()`, `_split_camel()`

2. **consult.py / revision.py / write.py (P14.1)**
   - Callers merge suspect citations from all audit stages
   - `suspect_citations` included in workflow results output

3. **runner.py (P14.2)**
   - Pre-read path now handles `bundle_targets: list[str]` (plural)
   - Concatenates multiple files with `%%% BEGIN FILE / END FILE %%%` markers

4. **BundleExplorer.tsx (P14.2)**
   - `BundleFileTree` and `TreeNodeRow` gain optional `multiSelect` mode with checkboxes

5. **PaperChatPage.tsx (P14.1 + P14.2)**
   - Batch mode toggle in file tree sidebar
   - ChatTurn displays `suspect_citations` warning with key/reason details
   - ChatTargetPicker supports batch multi-select
   - `bundle_targets` sent to backend when batch mode active

6. **aaf-engineering-framework/ (P14.2)**
   - NTFS Junction created: outer-level `aaf-engineering-framework/` → `academic-agent-framework/.cursor/`
   - `AGENTS.md` updated with outer junction reference
   - README.md added at junction root

### Verification
- `citation_guard.py`: consult/revision/write workflows no longer hard-fail on missing citations
- Frontend: select multiple files in bundle tree → "Review N files" → task created with `bundle_targets`
- Junction: `ls aaf-engineering-framework/` shows `.cursor/` contents
