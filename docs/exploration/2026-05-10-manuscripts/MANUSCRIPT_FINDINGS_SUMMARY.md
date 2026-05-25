# 📋 Backend Manuscript System Exploration — Complete Findings

**Status:** ✅ COMPLETE  
**Exploration Level:** Medium  
**Date:** 2026-05-10  
**Repository:** /Users/bizhiliang/Code/academic-agent-framework/

---

## Executive Summary

The backend manuscript system provides a **flat file listing API** with **POSIX-style relative paths** that encode directory structure implicitly. The system properly distinguishes between **copy mode** (AAF-owned, deleted on manuscript removal) and **link mode** (user-managed, preserved on deletion). The backend provides sufficient data for the frontend to build a hierarchical tree view by parsing paths.

---

## 🎯 Key Findings

### 1. ManuscriptFile Model — NO Directory Metadata

| Field | Type | Notes |
|-------|------|-------|
| `path` | `str` | POSIX-relative, e.g., `"sections/intro.md"` ✓ |
| `size` | `int` | File size in bytes |
| `mime` | `str` | MIME type guess from extension |
| `is_text` | `bool` | Text/binary classification |
| `sha256` | `str \| None` | Only if `include_hash=true` |
| `modified_at` | `datetime` | Last modification time (UTC) |
| **`is_dir`** | **NOT PRESENT** ❌ | No directory flag |

**Implication:** Directories are **implicit** in path structure; must split on `/` to build tree.

---

### 2. BundleManifest — Flat Structure

```python
BundleManifest {
    manuscript_id: str,
    layout: "bundle",
    root: str,                                      # Absolute path (informational)
    link_mode: bool,                                # Copy vs. link mode indicator
    file_count: int,
    total_size: int,
    files: list[ManuscriptFile]                     # ← FLAT, no nesting
}
```

**Key:** The `files` array is **always flat** — no hierarchical structure.

---

### 3. list_tree Implementation — Files Only

**File:** `backend/manuscripts/bundle_storage.py:282-344`

```python
# Core loop uses os.walk()
for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
    # Filters directories
    dirnames[:] = [d for d in dirnames if d not in self._ignore_dirs]
    
    # ONLY processes files
    for name in filenames:
        # ... validation ...
        rel = abs_path.relative_to(root).as_posix()  # Line 315
        files.append(ManuscriptFile(path=rel, ...))
```

**Result:** Only files returned; directories must be inferred from paths.

---

### 4. Path Format — POSIX Relative

### Examples of Returned Paths:
```
✓ "main.tex"
✓ "sections/intro.md"
✓ "figures/data/plots/scatter.png"
✓ "appendix/supplementary/table_a.csv"

✗ "/absolute/path/to/file.md"  (rejected)
✗ "../parent/dir/file.md"      (rejected)
✗ "sections/"                  (directories not listed)
```

**Enforcement:** Path validation in `BundleStorage._safe_resolve()` (lines 229-278)

---

### 5. DELETE Endpoint — Mode-Specific Behavior

#### Endpoint: `DELETE /api/manuscripts/{manuscript_id}`
**Location:** `backend/api/routers/manuscripts.py:213-237`

#### Algorithm:
```
1. Delete DB record (always)
2. IF layout != "bundle": return 204
3. ELSE:
   - IF bundle_link_path is None (COPY MODE):
       Call storage.remove_owned(record)
       → shutil.rmtree({root}/{id}/work)  ✅ DELETES
   - ELSE (LINK MODE):
       is_link_mode() returns early  → ⚠️ NO-OP
```

#### Mode Detection:
**File:** `backend/manuscripts/bundle_storage.py:172-173`
```python
def is_link_mode(self, manuscript: Manuscript) -> bool:
    return (manuscript.layout == "bundle" and 
            manuscript.bundle_link_path is not None)
```

#### Delete Summary Table:

| Mode | DB Deleted | Filesystem | Behavior |
|------|-----------|-----------|----------|
| **Single** | ✅ Yes | — | DB-only deletion |
| **Bundle (Copy)** | ✅ Yes | ✅ Deleted via `shutil.rmtree()` | AAF owns dir |
| **Bundle (Link)** | ✅ Yes | ❌ NO-OP (untouched) | User preserves dir |

---

## 📊 API Endpoint Summary

### GET /api/manuscripts/{id}/tree

**Query Parameters:**
- `include_hash: bool` (default: false) — compute SHA-256 per file
- `include_hidden: bool` (default: false) — include dotfiles + ignore dirs

**Response:** `BundleManifest` with flat `files` array

**Example:**
```bash
GET /api/manuscripts/ms_12345/tree
```

```json
{
  "manuscript_id": "ms_12345",
  "layout": "bundle",
  "link_mode": false,
  "file_count": 3,
  "total_size": 514524,
  "files": [
    {"path": "main.tex", "size": 2500, "mime": "text/plain", "is_text": true, ...},
    {"path": "sections/intro.md", "size": 1024, "mime": "text/markdown", "is_text": true, ...},
    {"path": "figures/plot.png", "size": 512000, "mime": "image/png", "is_text": false, ...}
  ]
}
```

---

### DELETE /api/manuscripts/{id}

**Return Code:** `204 No Content` (both modes)

**Side Effects:**
- ✅ Always: DB record + versions deleted
- ✅ Copy mode: Physical directory deleted via `shutil.rmtree()`
- ⚠️ Link mode: Physical directory untouched (user path preserved)

**Error Codes:**
- `404 Not Found` — manuscript doesn't exist
- `500 Internal Server Error` — OS error during cleanup (link mode error logged, not fatal)

---

## 🏗️ Architecture Insights

### BundleStorage Class
**Location:** `backend/manuscripts/bundle_storage.py`

**Key Methods:**
- `physical_root(manuscript)` → Resolves copy or link path
- `is_link_mode(manuscript)` → Mode detection
- `list_tree(...)` → Flat file enumeration
- `remove_owned(manuscript)` → Conditional directory deletion

**Safety Features:**
- Path containment validation (no `..` escapes)
- Symlink detection (no following outside root)
- Size caps enforcement (per-file, per-bundle)
- Atomic writes (`.tmp` files + `os.replace()`)

### Ignore Patterns
**File:** `backend/manuscripts/bundle_storage.py:67-70`

```python
DEFAULT_IGNORE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", 
    "node_modules", ".venv", ".idea", ".vscode"
}

DEFAULT_IGNORE_FILES = {".DS_Store", "Thumbs.db"}
```

Plus: Any file/directory starting with `.` (dotfiles)

---

## 🎨 Tree View Implementation Guide

### Current Backend Limitation
❌ Backend does NOT provide:
- Hierarchical/nested structure
- Directory entries in listing
- Directory-level metadata

### Frontend MUST Implement
✅ Tree building from flat path array:

```typescript
// Pseudocode
const flat = await fetch("/api/manuscripts/{id}/tree").then(r => r.json());
const tree = buildTreeFromPaths(flat.files);

function buildTreeFromPaths(files: ManuscriptFile[]): TreeNode {
    const root = { name: "root", children: [] };
    
    for (const file of files) {
        const parts = file.path.split("/");
        let current = root;
        
        // Create directory nodes
        for (let i = 0; i < parts.length - 1; i++) {
            const dir = parts[i];
            let node = current.children.find(c => c.name === dir);
            if (!node) {
                node = { name: dir, children: [] };
                current.children.push(node);
            }
            current = node;
        }
        
        // Add file
        current.children.push({
            name: parts[parts.length - 1],
            path: file.path,
            ...file
        });
    }
    
    return root;
}
```

---

## 🔒 Copy vs. Link Mode Deep Dive

### Copy Mode (Default)
```
Manuscript {
    layout: "bundle",
    bundle_link_path: None
}

Filesystem:
{settings.manuscript_root}/{manuscript_id}/work/
├── main.tex
├── sections/
│   └── intro.md
└── figures/
    └── plot.png

On Delete: ✅ Entire directory removed
```

### Link Mode (User Managed)
```
Manuscript {
    layout: "bundle",
    bundle_link_path: "/home/user/my-project"
}

Filesystem:
/home/user/my-project/
├── main.tex
├── sections/
│   └── intro.md
└── figures/
    └── plot.png

On Delete: ⚠️ NO-OP (user directory preserved)
```

**Purpose:** Link mode allows users to manage their project elsewhere (git, Overleaf, IDE) while AAF reads/writes in place.

---

## 📝 Code References

### Model Definitions
| Model | File | Lines |
|-------|------|-------|
| `ManuscriptFile` | `models.py` | 157-174 |
| `BundleManifest` | `models.py` | 176-188 |
| `Manuscript` | `models.py` | 40-76 |

### Storage Implementation
| Method | File | Lines |
|--------|------|-------|
| `list_tree()` | `bundle_storage.py` | 282-344 |
| `remove_owned()` | `bundle_storage.py` | 201-225 |
| `physical_root()` | `bundle_storage.py` | 157-170 |
| `is_link_mode()` | `bundle_storage.py` | 172-173 |

### Router Handlers
| Handler | File | Lines |
|---------|------|-------|
| `get_bundle_tree()` | `routers/manuscripts.py` | 501-520 |
| `delete_manuscript()` | `routers/manuscripts.py` | 213-237 |

---

## ✅ What's Already Implemented

1. ✅ **Flat file listing** with full relative paths
2. ✅ **Path validation** (no `..`, no absolute paths, containment checked)
3. ✅ **Text/binary detection** (MIME + extension heuristic)
4. ✅ **File metadata** (size, mtime, type, optional SHA-256)
5. ✅ **Ignore patterns** (.git, __pycache__, .venv, node_modules, etc.)
6. ✅ **Copy vs. link mode distinction** with proper deletion logic
7. ✅ **Size caps** (per-file, per-bundle)
8. ✅ **Atomic writes** (avoid half-written files)

---

## 🔧 Potential Enhancements

### For Better Hierarchical Support
1. **Add `is_dir` flag** to response (requires separate directory iteration)
2. **Add `?dir=` query parameter** for partial tree traversal
3. **Add directory metadata** (aggregated size, max mtime)
4. **Add tree format option** (`?format=tree` returns nested structure)

### For Better UX
1. **Streaming for large files** (currently buffers entire file)
2. **Directory-level operations** (mkdir, rmdir)
3. **Batch operations** (upload multiple files, delete subtree)

---

## 📌 Quick Checklist for Frontend

- [ ] Fetch `/api/manuscripts/{id}/tree` → get `BundleManifest`
- [ ] Check `link_mode` to understand copy vs. link mode
- [ ] Parse `files[].path` by splitting on `/`
- [ ] Build tree structure from path segments
- [ ] Display with expand/collapse UI
- [ ] On delete: Call `DELETE /api/manuscripts/{id}` → user gets 204
- [ ] Verify: Link mode deletes only DB, copy mode deletes physical dir

---

## 📚 Documentation Files Generated

1. **`MANUSCRIPT_BACKEND_ANALYSIS.md`** (410 lines)
   - Detailed code excerpts with line numbers
   - Model definitions with all fields
   - Implementation deep-dives
   
2. **`MANUSCRIPT_QUICK_REFERENCE.md`** (276 lines)
   - 10-section condensed reference
   - TypeScript tree-building example
   - Query parameters and error codes
   
3. **`MANUSCRIPT_ENDPOINT_FLOW.txt`** (145 lines)
   - Visual ASCII flowcharts
   - Request/response examples
   - Path transformation examples

---

## 🎓 Conclusion

The backend manuscript system is **well-designed for serving files** with:
- ✅ Strong path safety (no traversal, containment verified)
- ✅ Clear mode distinction (copy vs. link with proper cleanup)
- ✅ Rich metadata (MIME, size, text detection, timestamps)

The **hierarchical tree view must be built by the frontend** by parsing the flat path list. This is a **reasonable design decision** because:
1. Keeps backend simple and focused
2. Gives frontend control over tree visualization
3. Reduces backend complexity for directory metadata tracking
4. Flat list is easier to cache and paginate

The backend provides **all necessary data** for a full-featured hierarchical UI. Frontend implementation is straightforward: split paths on `/` and build nested structure.

