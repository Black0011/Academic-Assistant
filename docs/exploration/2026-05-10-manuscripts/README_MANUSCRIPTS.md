# 📚 Manuscript System Documentation Index

This directory contains comprehensive documentation of the backend manuscript system explored at **medium level** (2026-05-10).

## 📖 Documents

### 1. **MANUSCRIPT_FINDINGS_SUMMARY.md** ⭐ START HERE
**Best for:** Quick overview with all key findings  
**Length:** ~300 lines  
**Contains:**
- Executive summary
- 5 key findings (models, flat structure, delete logic, etc.)
- API endpoint summaries
- Tree view implementation guide
- Copy vs. link mode deep dive
- Frontend checklist

### 2. **MANUSCRIPT_QUICK_REFERENCE.md**
**Best for:** Developer reference while coding  
**Length:** ~276 lines  
**Contains:**
- 10 numbered sections (What does /tree return? Path formats? Delete logic?)
- TypeScript tree-building example
- Query parameters table
- Text/binary detection rules
- Size caps and limits
- File access patterns

### 3. **MANUSCRIPT_BACKEND_ANALYSIS.md**
**Best for:** Deep technical analysis with code excerpts  
**Length:** ~410 lines  
**Contains:**
- Code excerpts with exact line numbers
- Model definitions (ManuscriptFile, BundleManifest, Manuscript)
- list_tree() implementation details
- Tree endpoint handler code
- Delete endpoint implementation
- Full comparison tables

### 4. **MANUSCRIPT_ENDPOINT_FLOW.txt**
**Best for:** Visual understanding of request/response flows  
**Length:** ~145 lines  
**Contains:**
- ASCII flowcharts for GET /tree
- ASCII flowcharts for DELETE
- Request/response examples
- Path transformation examples
- Ignore patterns reference

## 🎯 Quick Answers

### What does `/api/manuscripts/{id}/tree` return?
→ See **MANUSCRIPT_QUICK_REFERENCE.md § 1** or **FINDINGS_SUMMARY.md § Key Finding #1**

### Does it include directory entries?
→ **NO** — only files. Directories are implicit in path structure (split on `/`)

### Does ManuscriptFile have `is_dir`?
→ **NO** — no directory flag in the model

### How does DELETE handle link vs. copy mode?
→ See **MANUSCRIPT_QUICK_REFERENCE.md § 7** or **FINDINGS_SUMMARY.md § Copy vs. Link Mode**

### What's the file path format?
→ POSIX-relative: `"sections/intro.md"` — See **MANUSCRIPT_QUICK_REFERENCE.md § 2**

### How do I build a hierarchical tree?
→ See **MANUSCRIPT_QUICK_REFERENCE.md § 4** with TypeScript example

## 🗂️ Code References

| File | Purpose | Key Methods |
|------|---------|-------------|
| `models.py:157-174` | ManuscriptFile | path, size, mime, is_text, sha256, modified_at |
| `models.py:176-188` | BundleManifest | files[], file_count, total_size, link_mode |
| `bundle_storage.py:282-344` | list_tree() | os.walk(), path conversion, ignore filtering |
| `bundle_storage.py:201-225` | remove_owned() | shutil.rmtree() (copy mode only) |
| `routers/manuscripts.py:501-520` | GET /tree | validation, storage.list_tree() call |
| `routers/manuscripts.py:213-237` | DELETE | mode detection, remove_owned() call |

## ✅ Key Takeaways

1. **Flat API** — `/tree` returns flat file list, not hierarchical tree
2. **POSIX paths** — Files use relative paths like `"sections/intro.md"`
3. **No directory metadata** — No `is_dir` field, no separate dir entries
4. **Frontend builds hierarchy** — Must split paths on `/` to build tree
5. **Mode-aware deletion** — Copy mode deletes filesystem, link mode preserves it
6. **Rich file metadata** — MIME type, text/binary flag, size, mtime, optional SHA-256
7. **Safety by default** — Path validation, ignore patterns, size caps

## 🛠️ For Frontend Developers

1. Fetch: `GET /api/manuscripts/{id}/tree`
2. Parse: Split `files[].path` by `/` to build tree nodes
3. Display: Render with expand/collapse UI
4. Delete: Call `DELETE /api/manuscripts/{id}` → returns 204
5. Files: Use `GET/PUT/POST/DELETE /files/{path:path}` for file operations

## 🔍 Navigation Tips

- **First time?** → Start with **FINDINGS_SUMMARY.md**
- **Coding?** → Keep **QUICK_REFERENCE.md** open
- **Deep dive?** → Read **BACKEND_ANALYSIS.md** with code
- **Visual learner?** → Check **ENDPOINT_FLOW.txt**

---

**Generated:** 2026-05-10 | **Repository:** /Users/bizhiliang/Code/academic-agent-framework/
