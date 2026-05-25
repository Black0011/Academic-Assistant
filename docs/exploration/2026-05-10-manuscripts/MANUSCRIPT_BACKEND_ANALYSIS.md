# Backend Manuscript System Analysis

**Exploration Level:** Medium  
**Date:** 2026-05-10  
**Repository:** /Users/bizhiliang/Code/academic-agent-framework/backend/

---

## 1. ManuscriptFile Model (models.py)

### Location
**File:** `backend/manuscripts/models.py`  
**Lines:** 157-174

### Model Definition
```python
class ManuscriptFile(BaseModel):
    """One file entry inside a bundled manuscript.

    Discovered by :meth:`BundleStorage.list_tree`. ``path`` is always a
    POSIX-style path **relative** to the bundle root — never absolute,
    never contains ``..`` segments. ``sha256`` is populated only when the
    caller asked for it (computing it is O(file size) per entry).
    """

    model_config = ConfigDict(extra="forbid")

    path: str  # POSIX, relative, no ".." — enforced by storage layer
    size: int  # bytes
    mime: str  # best-effort guess from extension
    is_text: bool  # decoder-friendly text vs binary
    sha256: str | None = None  # filled only when requested
    modified_at: datetime  # last mtime, UTC
```

### Key Findings
- **No directory flag:** ManuscriptFile does NOT have an `is_dir` field
- **Path format:** POSIX-style relative paths (e.g., `"experiments/data.csv"` or `"sections/intro.md"`)
- **Flat structure:** Only files are returned, not directories
- **Optional SHA256:** Only computed when explicitly requested (`include_hash=True`)
- **Metadata included:** MIME type, size, text detection, and modification time

---

## 2. BundleManifest Model (models.py)

### Location
**File:** `backend/manuscripts/models.py`  
**Lines:** 176-188

### Model Definition
```python
class BundleManifest(BaseModel):
    """Result envelope of ``GET /manuscripts/{id}/tree``."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    layout: ManuscriptLayout
    root: str  # absolute path on the host (informational; clients shouldn't trust)
    link_mode: bool
    file_count: int
    total_size: int
    files: list[ManuscriptFile]
```

### Key Findings
- **Flat file list:** Contains only `files: list[ManuscriptFile]` — **no hierarchical tree structure**
- **Metadata:** Total file count and bundle size
- **Layout info:** Indicates if bundle is "copy" or "link" mode
- **Ready for hierarchical view:** All data is present (paths with `/`); client must build hierarchy

---

## 3. list_tree Method (bundle_storage.py)

### Location
**File:** `backend/manuscripts/bundle_storage.py`  
**Lines:** 282-344

### Method Signature
```python
async def list_tree(
    self,
    manuscript: Manuscript,
    *,
    include_hash: bool = False,
    include_hidden: bool = False,
) -> BundleManifest:
    """Walk the bundle root and return a flat manifest of files.

    ``include_hash=True`` computes SHA-256 per file (slow for big
    bundles — opt-in). ``include_hidden=True`` keeps dotfiles + the
    default ignore set; otherwise we hide ``.git`` etc. for the UI.
    """
```

### Implementation Details

```python
def _walk() -> tuple[list[ManuscriptFile], int]:
    files: list[ManuscriptFile] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if not include_hidden:
            dirnames[:] = [
                d for d in dirnames if d not in self._ignore_dirs and not d.startswith(".")
            ]
        for name in filenames:
            if not include_hidden:
                if name in self._ignore_files or name.startswith("."):
                    continue
            abs_path = Path(dirpath) / name
            try:
                st = abs_path.stat()
            except OSError:
                # raced with deletion or permission glitch — skip
                continue
            rel = abs_path.relative_to(root).as_posix()  # ← Path format
            mime = _guess_mime(abs_path)
            is_text = _looks_textual(abs_path, mime)
            sha: str | None = None
            if include_hash:
                sha = _sha256_file(abs_path)
            files.append(
                ManuscriptFile(
                    path=rel,
                    size=int(st.st_size),
                    mime=mime,
                    is_text=is_text,
                    sha256=sha,
                    modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                )
            )
            total += int(st.st_size)
    files.sort(key=lambda f: f.path)
    return files, total

files, total = await asyncio.to_thread(_walk)
return BundleManifest(
    manuscript_id=manuscript.id,
    layout="bundle",
    root=str(root),
    link_mode=self.is_link_mode(manuscript),
    file_count=len(files),
    total_size=total,
    files=files,
)
```

### Key Findings

| Aspect | Details |
|--------|---------|
| **File enumeration** | Uses `os.walk()` recursively with `followlinks=False` (lines 300-332) |
| **Directory entries** | **NOT returned** — only files are added to the list |
| **Path format** | POSIX-style relative paths (`.as_posix()` on line 315) |
| **Examples** | `"sections/intro.md"`, `"figures/data.csv"`, `"main.tex"` |
| **Sorting** | Files sorted by path alphabetically (line 332) |
| **Ignore patterns** | Filters `DEFAULT_IGNORE_DIRS` and dotfiles (lines 301-304) |
| **Directory filtering** | Uses `dirnames[:] =` to prune unwanted branches from recursion (line 302) |

---

## 4. Tree Endpoint Handler (routers/manuscripts.py)

### Location
**File:** `backend/api/routers/manuscripts.py`  
**Lines:** 501-520

### Handler Definition
```python
@router.get(
    "/{manuscript_id}/tree",
    response_model=BundleManifest,
    summary="List every file in the bundle (flat)",
)
async def get_bundle_tree(
    manuscript_id: str,
    include_hash: bool = Query(False, description="Compute SHA-256 per file (slower)."),
    include_hidden: bool = Query(False, description="Include dotfiles + .git etc."),
    state: AppState = Depends(get_app_state),
) -> BundleManifest:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    try:
        return await storage.list_tree(
            record, include_hash=include_hash, include_hidden=include_hidden
        )
    except ManuscriptPathInvalid as exc:
        raise _aaf_to_http(exc) from exc
```

### Response Format Example
```json
{
  "manuscript_id": "ms_12345",
  "layout": "bundle",
  "root": "/home/user/.aaf/manuscripts/ms_12345/work",
  "link_mode": false,
  "file_count": 12,
  "total_size": 2048576,
  "files": [
    {
      "path": "experiments/data.csv",
      "size": 1024,
      "mime": "text/csv",
      "is_text": true,
      "sha256": null,
      "modified_at": "2026-05-10T15:30:45Z"
    },
    {
      "path": "figures/plot.png",
      "size": 512000,
      "mime": "image/png",
      "is_text": false,
      "sha256": null,
      "modified_at": "2026-05-10T14:20:15Z"
    },
    {
      "path": "main.tex",
      "size": 2500,
      "mime": "text/plain",
      "is_text": true,
      "sha256": null,
      "modified_at": "2026-05-10T16:00:00Z"
    }
  ]
}
```

---

## 5. Delete Manuscript Endpoint (routers/manuscripts.py)

### Location
**File:** `backend/api/routers/manuscripts.py`  
**Lines:** 213-237

### Handler Definition
```python
@router.delete(
    "/{manuscript_id}",
    status_code=204,
    summary="Delete manuscript (and all its versions)",
)
async def delete_manuscript(
    manuscript_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    storage = getattr(state, "bundle_storage", None)
    record = await store.get(manuscript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="manuscript not found")
    deleted = await store.delete(manuscript_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="manuscript not found")
    # Free disk for AAF-owned bundles. Link mode is left untouched so we
    # never clobber user-managed directories.
    if storage is not None and record.layout == "bundle":
        try:
            await storage.remove_owned(record)
        except ManuscriptIOError:
            log.exception("manuscript.delete.bundle_cleanup_failed", manuscript_id=manuscript_id)
    return Response(status_code=204)
```

### Delete Logic Details

#### Link vs. Copy Mode Handling
- **Copy mode** (`bundle_link_path is None`):
  - Calls `storage.remove_owned(record)` → **physically deletes** the bundle directory
  - Location: `{manuscript_root}/{id}/work/`
  
- **Link mode** (`bundle_link_path` set):
  - **NO-OP** → user's directory is left untouched
  - Only the database record is deleted
  - See `remove_owned` implementation below

### remove_owned Method (bundle_storage.py)

**File:** `backend/manuscripts/bundle_storage.py`  
**Lines:** 201-225

```python
async def remove_owned(self, manuscript: Manuscript) -> None:
    """Recursively delete the AAF-owned directory for a manuscript.

    No-op for link mode — we never touch the user's directory. Used by
    the manuscript ``DELETE`` endpoint to free disk space.
    """
    if manuscript.layout != "bundle":
        return
    if self.is_link_mode(manuscript):
        return
    owned = (self._root / manuscript.id).resolve()
    if not owned.exists():
        return

    def _rm() -> None:
        shutil.rmtree(owned, ignore_errors=False)

    try:
        await asyncio.to_thread(_rm)
    except OSError as exc:
        log.exception("manuscript.bundle.remove_failed", manuscript_id=manuscript.id)
        raise ManuscriptIOError(
            "failed to remove bundle directory", manuscript_id=manuscript.id
        ) from exc
    log.info("manuscript.bundle.removed", manuscript_id=manuscript.id, path=str(owned))
```

### Delete Behavior Summary

| Mode | Deletion Behavior |
|------|------------------|
| **Copy mode** | ✅ Entire directory under `{root}/{id}/` recursively deleted via `shutil.rmtree()` |
| **Link mode** | ⚠️ No-op — user's directory is **never touched** |
| **Single layout** | ✅ Only DB record deleted; no filesystem cleanup |
| **Database cleanup** | ✅ Always — versions, metadata all purged |

---

## 6. Current Capabilities vs. Frontend Needs

### ✅ What Backend Provides
1. **Flat file list** with full relative paths
2. **POSIX-style paths** enable hierarchical reconstruction (e.g., `"sections/intro.md"` → split by `/`)
3. **File metadata** — size, mime type, text/binary flag, modification time
4. **Optional hash computation** — SHA-256 on demand
5. **Proper delete handling** — respects link vs. copy distinction

### ⚠️ What Backend Does NOT Provide
1. **Directory entries** — only files returned
2. **Explicit hierarchy** — no `/api/manuscripts/{id}/tree?dir=sections` endpoint
3. **Directory metadata** — no separate stats for folders
4. **Sparse tree filtering** — must return all files or none

### 🔧 Modifications Needed for Hierarchical Tree View

#### Option 1: Backend Builds Hierarchy (Recommended if backend wants it)
Add a query parameter to `list_tree` to return a tree structure:

```python
async def list_tree(
    self,
    manuscript: Manuscript,
    *,
    include_hash: bool = False,
    include_hidden: bool = False,
    as_tree: bool = False,  # ← NEW
) -> BundleManifest | TreeManifest:  # ← NEW
    # ... existing code ...
    if as_tree:
        return _build_tree(files, manuscript.id)
    # existing flat return
```

#### Option 2: Frontend Builds Hierarchy (Current Status - Recommended)
Frontend uses path parsing:
```javascript
// From flat list: ["main.tex", "sections/intro.md", "figures/plot.png"]
// Build tree:
{
  "name": "root",
  "files": [
    { "name": "main.tex", "path": "main.tex", ... },
    {
      "name": "sections",
      "children": [
        { "name": "intro.md", "path": "sections/intro.md", ... }
      ]
    },
    {
      "name": "figures",
      "children": [
        { "name": "plot.png", "path": "figures/plot.png", ... }
      ]
    }
  ]
}
```

---

## 7. Summary & Recommendations

| Question | Answer |
|----------|--------|
| **Does ManuscriptFile have directory info?** | ❌ No `is_dir` field, only files returned |
| **Does list_tree return directories?** | ❌ Only files via `os.walk()` |
| **File path format?** | ✅ POSIX-relative, e.g., `"sections/intro.md"` |
| **Can hierarchical tree view be built?** | ✅ YES — frontend must parse paths |
| **Delete handles link mode correctly?** | ✅ YES — skips removal for link mode |
| **Delete handles copy mode correctly?** | ✅ YES — calls `shutil.rmtree()` |

### Immediate Frontend Implementation
The backend **already provides enough data** for a hierarchical tree view. The frontend should:
1. Fetch `/api/manuscripts/{id}/tree`
2. Parse the flat `files` array
3. Build a tree by splitting paths on `/`
4. Display with visual hierarchy (indentation, expand/collapse)

### Optional Backend Enhancements (Future)
1. Add `is_dir` to response envelope (requires filtering `os.walk` results)
2. Add `/api/manuscripts/{id}/tree?dir=sections` for partial tree traversal
3. Add directory-level metadata (modified_at as max of children, etc.)

