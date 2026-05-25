# Manuscript Management System Analysis

## TASK 1: MANUSCRIPT DELETION BEHAVIOR

### Delete Handler Flow (`backend/api/routers/manuscripts.py:213-237`)

**Overview:**
The delete endpoint (`DELETE /api/manuscripts/{manuscript_id}`) has TWO phases:
1. **Database deletion** - removes metadata record
2. **Bundle cleanup** - conditionally frees disk space

**Deletion Logic:**
```python
async def delete_manuscript(manuscript_id: str, state: AppState):
    store = _require_store(state)
    storage = getattr(state, "bundle_storage", None)
    record = await store.get(manuscript_id)  # ① Fetch before deletion
    if record is None:
        raise HTTPException(status_code=404)
    deleted = await store.delete(manuscript_id)  # ② Delete DB record
    if not deleted:
        raise HTTPException(status_code=404)
    
    # ③ Conditional cleanup - ONLY for owned bundles
    if storage is not None and record.layout == "bundle":
        try:
            await storage.remove_owned(record)  # Delegates decision
        except ManuscriptIOError:
            log.exception("manuscript.delete.bundle_cleanup_failed")
    return Response(status_code=204)
```

**Key Decision:** The endpoint fetches the record FIRST, then delegates cleanup to `BundleStorage.remove_owned()`.

---

### BundleStorage.remove_owned() (`backend/manuscripts/bundle_storage.py:201-225`)

**Purpose:** Safely delete only AAF-owned bundles (copy mode), skip user-managed directories (link mode).

**Implementation:**
```python
async def remove_owned(self, manuscript: Manuscript) -> None:
    """Recursively delete the AAF-owned directory for a manuscript.
    
    No-op for link mode — we never touch the user's directory. Used by
    the manuscript DELETE endpoint to free disk space.
    """
    # ① Reject non-bundle layouts (already enforced by caller, but defensive)
    if manuscript.layout != "bundle":
        return
    
    # ② CRITICAL: Check link mode - NO-OP if linked
    if self.is_link_mode(manuscript):
        return  # ← User's directory stays untouched!
    
    # ③ Only delete if owned (copy mode)
    owned = (self._root / manuscript.id).resolve()
    if not owned.exists():
        return
    
    def _rm() -> None:
        shutil.rmtree(owned, ignore_errors=False)
    
    try:
        await asyncio.to_thread(_rm)
    except OSError as exc:
        log.exception("manuscript.bundle.remove_failed")
        raise ManuscriptIOError(...)
    log.info("manuscript.bundle.removed", path=str(owned))
```

**Helper Method (`is_link_mode`):**
```python
def is_link_mode(self, manuscript: Manuscript) -> bool:
    return manuscript.layout == "bundle" and manuscript.bundle_link_path is not None
```

**Deletion Decision Matrix:**

| Scenario | Layout | Link Path | Behavior | Outcome |
|----------|--------|-----------|----------|---------|
| Single layout | "single" | None | Early return | DB only; no cleanup |
| Copy-mode bundle | "bundle" | None | Delete owned | `settings_root/<id>/` removed |
| Link-mode bundle | "bundle" | "/path/to/project" | Early return | DB only; linked dir preserved |

---

### Summary: Task 1 ✅

**Deletion is SAFE:**
1. ✅ **Single manuscripts:** DB record deleted, no file cleanup
2. ✅ **Copy-mode bundles:** AAF-owned directory (`settings_root/<id>/work`) recursively deleted
3. ✅ **Link-mode bundles:** Metadata deleted from DB, but user's linked directory is NEVER touched
   - `remove_owned()` checks `is_link_mode()` and returns early
   - The linked path stays on disk, user retains their directory

**Test Coverage Needed:**
- Verify link-mode deletion doesn't touch the source directory
- Verify copy-mode deletion cleans up `settings_root/<id>/`

---

## TASK 2: FRONTEND MANUSCRIPT UPLOAD/FOLDER UX

### Current Frontend Capabilities

#### ManuscriptsPage.tsx (Upload Options)

**Available Upload Entry Points:**

1. **Single File Upload** (`UploadButton`)
   - Accepts: `.md`, `.markdown`, `.txt`, `.pdf`
   - Creates single-layout manuscript (legacy)
   - Endpoint: `POST /api/manuscripts/upload`

2. **ZIP Archive Upload** (`UploadZipButton`)
   - Accepts: `.zip` files
   - Creates bundle-layout manuscript in copy mode
   - Endpoint: `POST /api/manuscripts/import-zip`
   - Auto-detects `overleaf/` subdir for export

3. **Import Local Folder** (`ImportFolderCard`)
   - UI element: Button with toggle card
   - Input: Local file path (text field)
   - Supports TWO modes:
     - **Copy mode:** AAF owns the files (default)
     - **Link mode:** AAF points to existing folder
   - Endpoint: `POST /api/manuscripts/import-folder`
   - Button: "Import Folder" (`FolderInput` icon)

**Import Folder Card Implementation:**
```tsx
function ImportFolderCard({ onDone }) {
  const [path, setPath] = useState("");        // Local path: /Users/.../paper-sqlskill-agent
  const [mode, setMode] = useState("copy");     // Toggle: copy | link
  const [title, setTitle] = useState("");       // Optional custom title

  const importMut = useMutation({
    mutationFn: () =>
      manuscriptsApi.importFolder({
        local_path: path.trim(),
        mode,                          // ← key decision: "copy" vs "link"
        title: title.trim() || undefined,
      }),
    onSuccess: (m) => {
      toast.success(`Imported "${m.title}"`);
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
      onDone();
    },
  });

  return (
    <Card>
      <CardContent>
        {/* Path input */}
        <Input
          value={path}
          placeholder="/Users/bizhiliang/Code/Academic-Agent/data/papers/..."
        />
        
        {/* Mode selector */}
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="copy">Copy (AAF owns the files)</option>
          <option value="link">Link (read/write in place)</option>
        </select>
        
        {/* Optional title override */}
        <Input value={title} placeholder="paper-dataagent-eval" />
        
        <Button onClick={() => importMut.mutate()}>Import</Button>
      </CardContent>
    </Card>
  );
}
```

---

#### API Client (frontend/src/lib/manuscripts.ts)

**Available Endpoints:**

```typescript
const manuscriptsApi = {
  // Single file upload
  upload(payload: { file: File; title?: string; ... }): Promise<ManuscriptEnvelope> {
    // POST /api/manuscripts/upload (FormData)
  },

  // ZIP import
  importZip(payload: { file: File; title?: string; ... }): Promise<Manuscript> {
    // POST /api/manuscripts/import-zip (FormData)
  },

  // ← MAIN: Folder import (copy OR link)
  importFolder(body: ImportFolderInput): Promise<Manuscript> {
    return api<Manuscript>(`/api/manuscripts/import-folder`, {
      method: "POST",
      json: body,  // { local_path, mode: "copy"|"link", title, ... }
    });
  },

  // Bundle lifecycle
  convertToBundle(id: string, body: BundleConvertInput = {}): Promise<Manuscript> {
    // POST /api/manuscripts/{id}/bundle
    // Converts single → bundle with optional link_path
  },

  // File tree listing (flat)
  tree(id: string, opts: { include_hash?: boolean; include_hidden?: boolean }): Promise<BundleManifest> {
    // GET /api/manuscripts/{id}/tree
    // Returns all files in flat list
  },

  // Individual file operations
  readFile(id: string, path: string, opts: { text?: boolean }): Promise<FileEnvelope> {
  writeTextFile(id: string, path: string, body: WriteFileInput): Promise<ManuscriptFile> {
  uploadBundleFile(id: string, path: string, file: File): Promise<ManuscriptFile> {
  deleteFile(id: string, path: string): Promise<void> {

  // Zip export
  exportZipUrl(id: string, opts: { subdir?: string; ... }): string {
    // GET /api/manuscripts/{id}/export-zip
    // Auto-detects overleaf/ subdir
  },
};
```

---

#### BundleExplorer.tsx (File Tree View)

**Architecture:**
- Two-pane layout: file tree (left ~18rem) + editor (right)
- Flat file listing with directory grouping headers
- Monaco editor integration for text files

**Tree Display:**
```tsx
function BundleExplorer({ manuscript }) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const treeQuery = useQuery({
    queryKey: ["bundle-tree", manuscript.id],
    queryFn: () => manuscriptsApi.tree(manuscript.id),
    // ↑ Returns BundleManifest with flat list of files
  });

  const filteredFiles = useMemo(() => {
    const all = treeQuery.data?.files ?? [];
    if (!filter.trim()) return all;
    return all.filter((f) => f.path.toLowerCase().includes(q));
  }, [treeQuery.data, filter]);

  return (
    <div className="grid grid-cols-[20rem_1fr] gap-4">
      {/* Left: Tree pane */}
      <Card>
        <Input
          value={filter}
          placeholder="Filter path..."  // ← Searchable flat list
        />
        <FileTree
          files={filteredFiles}
          selected={selectedPath}
          onSelect={setSelectedPath}
        />
      </Card>

      {/* Right: Editor pane */}
      <Card>
        {selectedPath ? (
          <FileEditor
            manuscriptId={manuscript.id}
            path={selectedPath}
          />
        ) : (
          <p>Select a file</p>
        )}
      </Card>
    </div>
  );
}
```

**FileTree Rendering Logic:**
```tsx
function FileTree({ files, selected, onSelect }) {
  // Group by top-level directory ONLY
  const groups = useMemo(() => {
    const out = new Map<string, ManuscriptFile[]>();
    for (const f of files) {
      const top = f.path.includes("/") ? f.path.split("/", 1)[0] : "";
      // ↑ Only groups by FIRST segment: "overleaf" for "overleaf/main.tex"
      const list = out.get(top);
      if (list) list.push(f);
      else out.set(top, [f]);
    }
    // Root files first, then alphabetical directories
    return [...out.entries()].sort(([a], [b]) => {
      if (a === "") return -1;
      if (b === "") return 1;
      return a.localeCompare(b);
    });
  }, [files]);

  return (
    <ul>
      {groups.map(([dir, list]) => (
        <li key={dir || "_root"}>
          {/* Directory header */}
          <div className="bg-muted text-xs uppercase">
            {dir ? <Folder /> : <FolderOpen />}
            {dir || "/"}
          </div>
          
          {/* Files under this directory */}
          {list.map((f) => (
            <button key={f.path} onClick={() => onSelect(f.path)}>
              <File />
              {f.path.split("/").pop()}  {/* Leaf name only */}
              {humanBytes(f.size)}
            </button>
          ))}
        </li>
      ))}
    </ul>
  );
}
```

**Key Limitation:** Groups ONLY by top-level directory. Nested folders (e.g., `overleaf/sections/methodology.tex`) are NOT expanded hierarchically—all appear in a flat list under "overleaf".

---

#### PaperWriterPage.tsx (Paper Detail View)

**Layout Decision:**

```tsx
export function PaperWriterPage() {
  const { manuscriptId } = useParams();

  const meta = useQuery({
    queryFn: () => manuscriptsApi.get(manuscriptId),
  });

  // ← CRITICAL BRANCH
  if (meta.data?.layout === "bundle") {
    return (
      <div className="flex flex-col h-screen">
        <PaperHeader manuscript={meta.data} />
        <BundleExplorer manuscript={meta.data} />  {/* ← File tree UI */}
      </div>
    );
  }

  // Single-layout manuscripts use the old timeline + editor UI
  return (
    <div className="grid grid-cols-[1fr_18rem]">
      <Card>
        {/* Monaco editor for manuscript.content */}
      </Card>
      <Card>
        {/* Version timeline sidebar */}
      </Card>
    </div>
  );
}
```

**Bundle Metadata Display:**
```tsx
function BundleHeaderMeta({ manuscript, manifestFileCount }) {
  const linked = manuscript.bundle_link_path !== null;
  
  return (
    <div className="flex gap-2 text-xs">
      <Badge variant={linked ? "warning" : "neutral"}>
        {linked ? <LinkIcon /> : null}
        {linked ? "Link Mode" : "Copy Mode"}
      </Badge>
      <span>{manifestFileCount} files</span>
      {linked ? (
        <span title={manuscript.bundle_link_path}>
          📁 {shortPath(manuscript.bundle_link_path)}
        </span>
      ) : (
        <span>Owned by AAF</span>
      )}
    </div>
  );
}
```

---

### API Endpoints Summary

| Endpoint | Method | Purpose | Frontend Used? |
|----------|--------|---------|---|
| `/api/manuscripts` | GET | List manuscripts | ✅ Yes |
| `/api/manuscripts` | POST | Create manuscript | ✅ Yes |
| `/api/manuscripts/{id}` | GET | Fetch metadata | ✅ Yes |
| `/api/manuscripts/{id}` | PATCH | Update metadata | ⚠️ Not directly from UI |
| `/api/manuscripts/{id}` | DELETE | Delete manuscript | ⚠️ Not shown in UI |
| `/api/manuscripts/upload` | POST | Upload .md/.pdf | ✅ Yes |
| `/api/manuscripts/import-folder` | POST | Import folder (copy/link) | ✅ Yes |
| `/api/manuscripts/import-zip` | POST | Import .zip | ✅ Yes |
| `/api/manuscripts/{id}/bundle` | POST | Convert single→bundle | ❌ No UI button |
| `/api/manuscripts/{id}/tree` | GET | List all files | ✅ Yes (in BundleExplorer) |
| `/api/manuscripts/{id}/files/{path:path}` | GET | Read file | ✅ Yes |
| `/api/manuscripts/{id}/files/{path:path}` | PUT | Write text file | ✅ Yes |
| `/api/manuscripts/{id}/files/{path:path}` | POST | Upload binary file | ✅ Yes |
| `/api/manuscripts/{id}/files/{path:path}` | DELETE | Delete file | ✅ Yes |
| `/api/manuscripts/{id}/export-zip` | GET | Download bundle as zip | ✅ Yes |

---

## ANSWERS TO USER'S QUESTIONS

### 1. Can the user link a local folder WITHOUT copying?

**✅ YES - FULLY SUPPORTED**

**How:**
1. Navigate to Manuscripts page
2. Click "Import Folder" button
3. Enter path: `/Users/bizhiliang/Code/Academic-Agent/data/papers/paper-sqlskill-agent`
4. Select **"Link"** mode (instead of Copy)
5. Click "Import"

**What happens:**
- Backend: Creates manuscript metadata with `bundle_link_path = "/Users/bizhiliang/..."`
- User's directory: NEVER copied, remains on disk managed by user
- AAF behavior: Reads/writes files in-place via the link
- Deletion: If user deletes manuscript from AAF, the linked folder is preserved

**Backend Implementation:**
```python
@router.post("/import-folder")
async def import_folder(body: ImportFolderInput):
    # ...
    create_body = CreateManuscriptInput(
        title=body.title or source.name,
        layout="bundle",
        bundle_link_path=str(source) if body.mode == "link" else None,
        # ↑ If mode="link", store the path; if mode="copy", None
        bundle_versioning=body.mode == "copy",
    )
    record, _ = await store.create(create_body)

    if body.mode == "copy":
        await storage.import_directory(record, source)
    else:
        # Link mode: just validate the path exists
        await storage.init_for(record)
```

---

### 2. Does the frontend have a way to browse subfolders and files?

**❌ PARTIAL - Flat list with top-level grouping**

**Current Behavior:**
- ✅ **File listing:** All files shown in a flat list
- ✅ **First-level grouping:** Files grouped by top-level directory (e.g., "overleaf", "sections", root)
- ❌ **Nested navigation:** No hierarchical tree expansion
  - Cannot click "overleaf/" to expand and see nested folders
  - Cannot expand "overleaf/sections/" to see `.tex` files inside
  - All nested paths shown as flat entries: "overleaf/sections/methodology.tex" appears as a single line

**Example Display:**

```
OVERLEAF GROUP
  overleaf/main.tex           [3.2 KB]
  overleaf/sections/intro.tex [2.5 KB]      ← nested, but not expandable
  overleaf/sections/methods.tex [5.1 KB]
  overleaf/figs/fig1.png      [45 KB]

EXPERIMENTS GROUP
  experiments/results.json    [1.2 MB]
  experiments/log_2024.csv    [250 KB]

ROOT FILES
  README.md                   [1.5 KB]
  .gitignore                  [0.5 KB]
```

**Filtering:**
- ✅ Text search: Filter by filename or path substring
- Example: Type "methodology" → shows only "overleaf/sections/methodology.tex"

**What's Missing:**
1. ❌ Folder expand/collapse UI
2. ❌ Click-to-navigate folders (visual directory tree)
3. ❌ Breadcrumb navigation while editing nested files
4. ❌ Folder-level operations (create subfolder, move files, bulk delete)

---

### 3. What's missing to support the user's workflow?

**User Workflow Goal:**
> Manage paper projects with subfolders:
> - `/papers/paper-sqlskill-agent/`
>   - `overleaf/` (Overleaf-synced LaTeX)
>   - `experiments/` (data, logs, scripts)
>   - `reviewer-comments/` (reviewer feedback, rebuttals)
>   - `notes/` (working notes, ideas)
>   - `README.md`, `CHANGELOG.md`

**Current Gaps:**

| Feature | Status | Impact | Workaround |
|---------|--------|--------|-----------|
| Link mode support | ✅ Works | Can point AAF to existing folder | Use `/api/manuscripts/import-folder` with `mode="link"` |
| File tree API | ✅ Works | Backend returns all files | Already implemented |
| Flat file listing | ✅ Works | Frontend shows all files | Good for search-driven access |
| Hierarchical tree UI | ❌ Missing | Hard to navigate deep folders | User must know exact file path or search |
| Folder navigation | ❌ Missing | Cannot browse folders visually | Flat list + text filter workaround |
| Bulk folder ops | ❌ Missing | Cannot create/delete folders | Use external editor (VSCode, Finder) |
| Breadcrumb navigation | ❌ Missing | No context while editing nested files | Show full path in editor header |
| Folder-aware filtering | ❌ Missing | Cannot "show only experiments/" | Text search is only option |

---

### Missing Features (Priority for User Workflow)

#### HIGH PRIORITY (Big UX Win)

**1. Hierarchical Tree View Component**
- Replace flat list with expandable folder tree
- Click folder icon to toggle expanded state
- Show nested hierarchy: `overleaf/` > `sections/` > `methodology.tex`
- Filter preserves folder structure

**Implementation Approach:**
```typescript
// Transform flat list into tree structure
function buildTree(files: ManuscriptFile[]): TreeNode[] {
  // Input: ["overleaf/main.tex", "overleaf/sections/intro.tex", "README.md"]
  // Output: [
  //   { type: "dir", name: "overleaf", children: [
  //     { type: "file", name: "main.tex", path: "overleaf/main.tex" },
  //     { type: "dir", name: "sections", children: [
  //       { type: "file", name: "intro.tex", path: "overleaf/sections/intro.tex" }
  //     ]}
  //   ]},
  //   { type: "file", name: "README.md", path: "README.md" }
  // ]
}

// Render tree with expand/collapse
function TreeNode({ node, onSelect }) {
  const [expanded, setExpanded] = useState(false);
  
  if (node.type === "file") {
    return <button onClick={() => onSelect(node.path)}>{node.name}</button>;
  }
  
  return (
    <div>
      <button onClick={() => setExpanded(!expanded)}>
        {expanded ? "📂" : "📁"} {node.name}
      </button>
      {expanded && node.children?.map(child => (
        <TreeNode key={child.name} node={child} onSelect={onSelect} />
      ))}
    </div>
  );
}
```

**2. Breadcrumb Navigation in Editor**
- Show full path while editing nested files
- Click segment to jump up folder levels
- Example: `overleaf / sections / methodology.tex`

```tsx
// In FileEditor header
<Breadcrumb path={path} onChange={onSelectPath}>
  {/* overleaf / sections / methodology.tex */}
</Breadcrumb>
```

---

#### MEDIUM PRIORITY (Nice to Have)

**3. Folder Context Menu**
- Right-click folder → "Create file here", "Create subfolder"
- Shorthand for creating files in nested paths

**4. Folder-Aware Upload**
- "Upload to folder" dialog
- Drag-drop folder contents

**5. Folder Statistics**
- Show file count, total size per top-level folder
- Example: "overleaf/ (23 files, 2.5 MB)"

---

#### LOW PRIORITY (Advanced)

**6. Project Structure Templates**
- "New project" button with preset folder layouts
- Example: "Overleaf Project" → creates `overleaf/`, `figures/`, `data/`

**7. Folder Diff / Sync Status**
- For link mode: show which files changed since last refresh
- Useful when files edited externally

**8. Git Integration (Link Mode)**
- Show git status, recent commits
- "View in GitHub" for linked git repos

---

## Architecture Summary

```
User's Disk                           AAF System
─────────────────────────────────────────────────

/path/to/paper/                       
  ├── overleaf/                       
  ├── experiments/        ──link──→   Manuscript (bundle, link_mode=true)
  ├── notes/                          ├─ bundle_link_path = "/path/to/paper"
  └── README.md                       └─ BundleStorage: reads/writes in place
                                      
                                      Frontend (BundleExplorer)
                                      ├─ Flat file list (current)
                                      ├─ Top-level grouping
                                      └─ Missing: hierarchical tree UI
```

---

## Conclusion

**Current State:**
- ✅ Backend fully supports link mode (copy and link both work)
- ✅ Deletion is safe (link mode directories preserved)
- ✅ File tree API returns all files in flat list
- ✅ Frontend can list, search, and edit files
- ❌ Frontend lacks hierarchical tree view for easy folder navigation

**For User's Workflow:**
The system CAN link `/Users/bizhiliang/Code/Academic-Agent/data/papers/paper-sqlskill-agent` and manage all subfolders. However, the UI requires text search to find nested files—a proper tree view would greatly improve usability.

**Recommended Next Steps:**
1. Build hierarchical tree view component (medium effort, high UX impact)
2. Add breadcrumb navigation in editor (low effort)
3. Optionally add "create folder" / "move file" UI later

