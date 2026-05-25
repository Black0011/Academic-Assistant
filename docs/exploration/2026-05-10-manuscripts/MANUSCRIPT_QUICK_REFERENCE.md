# Backend Manuscript System — Quick Reference

## 1️⃣ What Does `/api/manuscripts/{id}/tree` Return?

### Response Type: `BundleManifest`
```python
BundleManifest(
    manuscript_id: str,
    layout: "bundle",
    root: str,              # absolute path
    link_mode: bool,        # true = link mode, false = copy mode
    file_count: int,
    total_size: int,
    files: list[ManuscriptFile]  # ← FLAT list only
)
```

### Each File in `files`:
```python
ManuscriptFile(
    path: str,                      # "sections/intro.md" ← POSIX relative!
    size: int,                      # bytes
    mime: str,                      # "text/markdown"
    is_text: bool,                  # true for text, false for binary
    sha256: str | None,             # Only if include_hash=true
    modified_at: datetime           # UTC ISO timestamp
)
```

### Important: NO DIRECTORIES
- Only **files** returned, not directory entries
- Directories are implicit in the path structure (split on `/`)
- If you see `"sections/intro.md"`, you know `sections/` exists

---

## 2️⃣ Path Format Details

### What You Get
```json
{
  "path": "experiments/data/results.csv"
}
```

### What You Don't Get
- ❌ Absolute paths (no `/home/user/...`)
- ❌ Parent traversal (no `../` sequences)
- ❌ Directory entries (no `"experiments/"` or `"experiments/data/"`)

### Code: How Paths Are Generated
**File:** `backend/manuscripts/bundle_storage.py:315`
```python
rel = abs_path.relative_to(root).as_posix()  # ← Converts to POSIX
```

---

## 3️⃣ Delete Endpoint Behavior

### Endpoint: `DELETE /api/manuscripts/{manuscript_id}`

### Deletion Logic
```
IF layout == "single":
    → Delete DB record only ✓

IF layout == "bundle":
    ├─ Always delete DB record ✓
    │
    └─ Check bundle_link_path:
        ├─ None (copy mode):
        │   → DELETE physical directory (shutil.rmtree) ✓
        │   → Path: {root}/{id}/work/*
        │
        └─ SET (link mode):
            → NO-OP ⚠️ (user directory left untouched)
```

### Code: Mode Detection
**File:** `backend/manuscripts/bundle_storage.py:172-173`
```python
def is_link_mode(self, manuscript: Manuscript) -> bool:
    return manuscript.layout == "bundle" and manuscript.bundle_link_path is not None
```

### Return Code
Both modes return `204 No Content` (success)

---

## 4️⃣ Hierarchical Tree Construction

### ❌ Backend Does NOT Provide
- Nested tree structure
- Directory metadata (mtime, size)
- Partial tree queries (e.g., `?dir=sections`)

### ✅ Frontend MUST Do This
1. Fetch `/api/manuscripts/{id}/tree`
2. Parse flat `files` array
3. Split each path on `/` to build hierarchy
4. Display with tree visualization (expand/collapse)

### Example Tree Building (TypeScript)
```typescript
interface TreeNode {
  name: string;
  path?: string;              // file path
  children?: TreeNode[];      // directories
  size?: number;
  mime?: string;
}

function buildTree(files: ManuscriptFile[]): TreeNode {
  const root: TreeNode = { name: "root", children: [] };
  
  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;
    
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      let dir = current.children?.find(c => c.name === part);
      
      if (!dir) {
        dir = { name: part, children: [] };
        current.children = current.children || [];
        current.children.push(dir);
      }
      current = dir;
    }
    
    current.children = current.children || [];
    current.children.push({
      name: parts[parts.length - 1],
      path: file.path,
      size: file.size,
      mime: file.mime
    });
  }
  
  return root;
}
```

---

## 5️⃣ Query Parameters

### GET /api/manuscripts/{id}/tree

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `include_hash` | bool | false | Compute SHA-256 for each file (slower) |
| `include_hidden` | bool | false | Include dotfiles + ignore dirs (.git, __pycache__) |

### Example: With Hashes
```
GET /api/manuscripts/ms_12345/tree?include_hash=true
```

→ Each file gets `sha256: "abc123..."` instead of `null`

---

## 6️⃣ Ignore Patterns (Always Applied Unless `include_hidden=true`)

### Directories Filtered
```python
DEFAULT_IGNORE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", 
    "node_modules", ".venv", ".idea", ".vscode"
}
```

### Files Filtered
```python
DEFAULT_IGNORE_FILES = {".DS_Store", "Thumbs.db"}
```

Plus: Any file/dir starting with `.` (dotfiles)

---

## 7️⃣ Copy vs. Link Mode

### Copy Mode: `bundle_link_path = None`
- AAF owns the directory
- Path: `{settings.manuscript_root}/{manuscript_id}/work/`
- On delete: ✅ **Recursively removed**
- Good for: Self-contained, portable manuscripts

### Link Mode: `bundle_link_path = "/path/to/user/project"`
- User manages the directory (git, Overleaf, IDE)
- AAF reads/writes in place
- On delete: ⚠️ **NO-OP** (user directory preserved)
- Good for: Existing projects, shared workflows

### Detection Code
**File:** `backend/api/routers/manuscripts.py:232-234`
```python
if storage is not None and record.layout == "bundle":
    try:
        await storage.remove_owned(record)
```

---

## 8️⃣ Text vs. Binary Detection

### Heuristic: MIME + Extension
**File:** `backend/manuscripts/bundle_storage.py:75-106`

#### Detected as Text:
- All `text/*` MIME types
- JSON, XML, YAML, TOML, JavaScript
- `.md`, `.tex`, `.py`, `.sh`, `.rs`, `.go`, etc.

#### Detected as Binary:
- All other extensions + unknown MIME types
- Default: `application/octet-stream`

### Usage: Frontend Preview Logic
```typescript
if (file.is_text) {
  // Show inline preview
  const content = await fetch(`/api/manuscripts/${id}/files/${file.path}`);
  // content.encoding === "utf-8"
} else {
  // Offer download button
  const download = `/api/manuscripts/${id}/download/${file.path}`;
}
```

---

## 9️⃣ Size Caps & Limits

### Per-File Cap
**Default:** 50 MB (configurable via `manuscript_max_file_mb`)

### Per-Bundle Cap
**Default:** 500 MB (configurable via `manuscript_max_bundle_mb`)

### Error Codes
- `413 Payload Too Large` — file or bundle exceeds cap

---

## 🔟 Accessing Files vs. Tree

| Operation | Endpoint | Returns |
|-----------|----------|---------|
| **List all files** | `GET /tree` | Flat `BundleManifest` |
| **Read text file** | `GET /files/{path}` | `FileEnvelope` (JSON) |
| **Read binary file** | `GET /files/{path}?text=false` | Base64-encoded JSON or raw bytes |
| **Write text file** | `PUT /files/{path}` | `ManuscriptFile` metadata |
| **Upload binary** | `POST /files/{path}` | `ManuscriptFile` metadata |
| **Delete file** | `DELETE /files/{path}` | `204 No Content` |

### Example: Read a File
```bash
# Text file (auto-detected)
curl https://api.example.com/api/manuscripts/ms_123/files/main.tex
# → FileEnvelope { file: ManuscriptFile, encoding: "utf-8", content: "..." }

# Force binary
curl https://api.example.com/api/manuscripts/ms_123/files/plot.png?text=false
# → FileEnvelope { file: ManuscriptFile, encoding: "base64", content: "iVBORw0..." }

# Download raw
curl https://api.example.com/api/manuscripts/ms_123/download/plot.png
# → binary PNG data (no JSON envelope)
```

