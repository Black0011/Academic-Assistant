"""Deep analysis queries against the code index database."""
import sqlite3
import json

DB = "E:/Academic-Agent-F/academic-agent-framework/.code-reading/index.db"
ROOT = "E:/Academic-Agent-F/academic-agent-framework/"
ROOT_BS = "E:\\Academic-Agent-F\\academic-agent-framework\\"

def short(path):
    for prefix in (ROOT_BS, ROOT, ROOT.replace("/", "\\")):
        path = path.replace(prefix, "")
    if len(path) > 70:
        path = "..." + path[-67:]
    return path

conn = sqlite3.connect(DB)

# 1. Module dependency matrix
print("=" * 70)
print("  1. CROSS-MODULE IMPORT ANALYSIS")
print("=" * 70)
imports_by_src = {}
for row in conn.execute("SELECT file_path, imported_module FROM imports"):
    path, mod = row[0], row[1]
    if "backend" in path:
        parts = path.replace("\\", "/").split("backend/")
        src = "backend/" + parts[1].split("/")[0] if len(parts) > 1 else "backend-root"
    elif "frontend" in path:
        parts = path.replace("\\", "/").split("frontend/")
        src = "frontend/" + parts[1].split("/")[0] if len(parts) > 1 else "frontend-root"
    elif "sdk/" in path or "sdk\\" in path:
        src = "sdk"
    else:
        src = path.replace("\\", "/").split("/")[0] if "/" in path.replace("\\", "/") else "other"
    imports_by_src.setdefault(src, {"internal": 0, "external": 0})
    if "backend" in mod:
        imports_by_src[src]["internal"] += 1
    else:
        imports_by_src[src]["external"] += 1

for src, counts in sorted(imports_by_src.items()):
    print(f"  {src:<30} internal={counts['internal']:>5}  external={counts['external']:>4}")

# 2. Layer violations
print()
print("=" * 70)
print("  2. LAYER VIOLATIONS (core/ importing agents/workflows/api)")
print("=" * 70)
violations = conn.execute(
    "SELECT file_path, imported_module FROM imports "
    "WHERE file_path LIKE '%backend/core%' AND ("
    "  imported_module LIKE '%backend.agents%' OR"
    "  imported_module LIKE '%backend.workflows%' OR"
    "  imported_module LIKE '%backend.api%'"
    ") ORDER BY file_path"
).fetchall()
if violations:
    for path, mod in violations:
        print(f"  VIOLATION: {short(path)} -> {mod}")
    print(f"  TOTAL VIOLATIONS: {len(violations)}")
else:
    print("  None found -- layer discipline maintained.")

# 3. Giant files (>400 LOC) by module
print()
print("=" * 70)
print("  3. FILES > 400 LOC (candidates for splitting)")
print("=" * 70)
giants = conn.execute("SELECT path, loc FROM d1_files WHERE loc > 400 ORDER BY loc DESC").fetchall()
by_module = {}
for path, loc in giants:
    s = short(path)
    mod = s.split("/")[0] if "/" in s else "(root)"
    by_module.setdefault(mod, []).append((s, loc))
for mod in sorted(by_module):
    total_giant = sum(loc for _, loc in by_module[mod])
    print(f"  [{mod}] {len(by_module[mod])} files, {total_giant} LOC total:")
    for s, loc in by_module[mod]:
        print(f"    {loc:>5} LOC  {s}")

# 4. Most tightly coupled modules (co-import)
print()
print("=" * 70)
print("  4. MODULE COUPLING STRENGTH")
print("=" * 70)
# Count files in one module importing from another
coupling = conn.execute("""
    SELECT
        CASE WHEN i.file_path LIKE '%backend/core%' THEN 'core'
             WHEN i.file_path LIKE '%backend/api%' THEN 'api'
             WHEN i.file_path LIKE '%backend/agents%' THEN 'agents'
             WHEN i.file_path LIKE '%backend/workflows%' THEN 'workflows'
             WHEN i.file_path LIKE '%backend/memory%' THEN 'memory'
             WHEN i.file_path LIKE '%backend/tools%' THEN 'tools'
             WHEN i.file_path LIKE '%backend/tasks%' THEN 'tasks'
             WHEN i.file_path LIKE '%backend/planner%' THEN 'planner'
             WHEN i.file_path LIKE '%backend/proposals%' THEN 'proposals'
             WHEN i.file_path LIKE '%backend/knowledge%' THEN 'knowledge'
             WHEN i.file_path LIKE '%backend/manuscripts%' THEN 'manuscripts'
             ELSE 'other'
        END as src_module,
        i.imported_module as tgt,
        COUNT(*) as cnt
    FROM imports i
    WHERE i.imported_module LIKE 'backend%'
    GROUP BY src_module
    ORDER BY cnt DESC
""").fetchall()
for src, tgt, cnt in coupling:
    print(f"  {src:<20} imports from backend modules: {cnt:>5}")

# 5. Function density (files with most functions/methods)
print()
print("=" * 70)
print("  5. FUNCTION DENSITY HOTSPOTS")
print("=" * 70)
dense = conn.execute("""
    SELECT f.path, COUNT(d.id) as cnt, f.loc
    FROM d0_functions d JOIN d1_files f ON d.file_id = f.id
    GROUP BY f.id HAVING cnt > 15
    ORDER BY cnt DESC
""").fetchall()
for path, cnt, loc in dense:
    ratio = loc / cnt if cnt else 0
    print(f"  {cnt:>4} funcs, {loc:>5} LOC ({ratio:.0f} LOC/func)  {short(path)}")

# 6. Summary stats
print()
print("=" * 70)
print("  6. SUMMARY")
print("=" * 70)
total_files = conn.execute("SELECT COUNT(*) FROM d1_files").fetchone()[0]
total_funcs = conn.execute("SELECT COUNT(*) FROM d0_functions").fetchone()[0]
total_loc = conn.execute("SELECT SUM(loc) FROM d1_files").fetchone()[0]
direct_calls = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='direct'").fetchone()[0]
ext_calls = conn.execute("SELECT COUNT(*) FROM calls WHERE relationship='external'").fetchone()[0]
py_files = conn.execute("SELECT COUNT(*) FROM d1_files WHERE language='python'").fetchone()[0]
ts_files = conn.execute("SELECT COUNT(*) FROM d1_files WHERE language IN ('typescript','tsx')").fetchone()[0]
print(f"  Python files:     {py_files:>6}")
print(f"  TypeScript files: {ts_files:>6}")
print(f"  Total files:      {total_files:>6}")
print(f"  Total functions:  {total_funcs:>6}")
print(f"  Total LOC:        {total_loc:>6}")
print(f"  Direct call edges:{direct_calls:>6}")
print(f"  External calls:   {ext_calls:>6}")
print(f"  Avg LOC/file:     {total_loc//total_files if total_files else 0:>6}")
print(f"  Avg funcs/file:   {total_funcs//total_files if total_files else 0:>6}")

conn.close()
print()
print("Done.")
