"""Integration tests for `/api/manuscripts` (CRUD + upload + export)."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.store import InMemoryManuscriptStore
from backend.memory import MemoryBundle
from backend.settings import Settings


@pytest.fixture
async def client(tmp_path):
    store = InMemoryManuscriptStore()
    await store.init()
    bundle_storage = BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=2 * 1024 * 1024,
        max_bundle_bytes=8 * 1024 * 1024,
    )
    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
        manuscripts=store,
        bundle_storage=bundle_storage,
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_without_content(client):
    r = await client.post(
        "/api/manuscripts",
        json={"title": "Empty draft", "kind": "paper"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["manuscript"]["title"] == "Empty draft"
    assert body["manuscript"]["current_version"] == 0
    assert body["version"] is None


async def test_create_with_content_commits_v1(client):
    r = await client.post(
        "/api/manuscripts",
        json={
            "title": "Intro",
            "content": "# Intro\n\nHello.",
            "tags": ["draft"],
            "note": "seed",
        },
    )
    assert r.status_code == 201
    body = r.json()
    mid = body["manuscript"]["id"]
    assert body["manuscript"]["current_version"] == 1
    assert body["version"]["version"] == 1
    assert body["version"]["note"] == "seed"

    # Fetch back
    r2 = await client.get(f"/api/manuscripts/{mid}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Intro"


async def test_get_missing_returns_404(client):
    r = await client.get("/api/manuscripts/nope")
    assert r.status_code == 404


async def test_list_filters(client):
    await client.post("/api/manuscripts", json={"title": "A", "user_id": "u1", "tags": ["x"]})
    await client.post("/api/manuscripts", json={"title": "B", "user_id": "u2"})
    await client.post("/api/manuscripts", json={"title": "C", "user_id": "u1", "tags": ["y"]})

    r = await client.get("/api/manuscripts", params={"user_id": "u1"})
    assert r.status_code == 200
    body = r.json()
    titles = sorted(m["title"] for m in body["items"])
    assert titles == ["A", "C"]

    r = await client.get("/api/manuscripts", params={"tag": "y"})
    assert [m["title"] for m in r.json()["items"]] == ["C"]


async def test_patch_updates_metadata(client):
    create = await client.post("/api/manuscripts", json={"title": "Old"})
    mid = create.json()["manuscript"]["id"]

    r = await client.patch(
        f"/api/manuscripts/{mid}",
        json={"title": "New", "status": "in_revision", "tags": ["r1"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New"
    assert body["status"] == "in_revision"
    assert body["tags"] == ["r1"]


async def test_patch_missing_returns_404(client):
    r = await client.patch("/api/manuscripts/nope", json={"title": "x"})
    assert r.status_code == 404


async def test_delete_removes_manuscript(client):
    create = await client.post("/api/manuscripts", json={"title": "Bye", "content": "x"})
    mid = create.json()["manuscript"]["id"]
    r = await client.delete(f"/api/manuscripts/{mid}")
    assert r.status_code == 204
    assert (await client.get(f"/api/manuscripts/{mid}")).status_code == 404


async def test_delete_missing_returns_404(client):
    r = await client.delete("/api/manuscripts/nope")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


async def test_commit_and_list_versions(client):
    create = await client.post("/api/manuscripts", json={"title": "Doc", "content": "v1"})
    mid = create.json()["manuscript"]["id"]

    r = await client.post(
        f"/api/manuscripts/{mid}/versions",
        json={"content": "v2", "note": "rev1", "origin": "revision_workflow"},
    )
    assert r.status_code == 201
    assert r.json()["version"] == 2

    r = await client.get(f"/api/manuscripts/{mid}/versions")
    assert r.status_code == 200
    versions = r.json()["items"]
    assert [v["version"] for v in versions] == [2, 1]

    r = await client.get(f"/api/manuscripts/{mid}/versions/1")
    assert r.status_code == 200
    assert r.json()["content"] == "v1"

    r = await client.get(f"/api/manuscripts/{mid}/versions/99")
    assert r.status_code == 404


async def test_commit_to_missing_manuscript_404(client):
    r = await client.post(
        "/api/manuscripts/nope/versions",
        json={"content": "x"},
    )
    assert r.status_code == 404


async def test_export_returns_markdown_with_frontmatter(client):
    create = await client.post(
        "/api/manuscripts", json={"title": "Paper", "content": "# Body\n\nHello."}
    )
    mid = create.json()["manuscript"]["id"]

    r = await client.get(f"/api/manuscripts/{mid}/export")
    assert r.status_code == 200
    text = r.text
    assert text.startswith("---\n")
    assert "title: Paper" in text
    assert "version: 1" in text
    assert "# Body" in text
    assert r.headers["content-type"].startswith("text/markdown")


async def test_export_no_versions_returns_404(client):
    create = await client.post("/api/manuscripts", json={"title": "Empty"})
    mid = create.json()["manuscript"]["id"]
    r = await client.get(f"/api/manuscripts/{mid}/export")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def test_upload_markdown_creates_manuscript_and_v1(client):
    payload = b"# Uploaded\n\nThis is a test."
    files = {"file": ("draft.md", payload, "text/markdown")}
    r = await client.post("/api/manuscripts/upload", files=files, data={"kind": "paper"})
    assert r.status_code == 201
    body = r.json()
    assert body["manuscript"]["title"] == "draft"
    assert body["version"]["version"] == 1
    assert "Uploaded" in body["version"]["content"]


async def test_upload_pdf_extracts_text(client):
    pdf_bytes = _build_minimal_pdf("Hello PDF content")
    files = {"file": ("paper.pdf", pdf_bytes, "application/pdf")}
    r = await client.post("/api/manuscripts/upload", files=files, data={"title": "From PDF"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["manuscript"]["title"] == "From PDF"
    assert body["version"] is not None
    assert "Hello PDF content" in body["version"]["content"]
    # Page heading in the markdown body.
    assert "## Page 1" in body["version"]["content"]


async def test_upload_rejects_unsupported_extension(client):
    files = {"file": ("data.bin", b"\x00\x01\x02", "application/octet-stream")}
    r = await client.post("/api/manuscripts/upload", files=files)
    assert r.status_code == 415


async def test_upload_rejects_empty(client):
    files = {"file": ("empty.md", b"", "text/markdown")}
    r = await client.post("/api/manuscripts/upload", files=files)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 503 when not wired
# ---------------------------------------------------------------------------


async def test_503_when_manuscripts_not_wired():
    state = AppState(settings=Settings(), memory=MemoryBundle.in_memory())
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/manuscripts")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# P7 — Bundle endpoints (file tree CRUD on project-shaped manuscripts)
# ---------------------------------------------------------------------------


async def _create_bundle(client, *, link_path: str | None = None) -> str:
    create = await client.post(
        "/api/manuscripts",
        json={"title": "Bundle paper", "kind": "paper"},
    )
    assert create.status_code == 201, create.text
    mid = create.json()["manuscript"]["id"]
    body: dict[str, object] = {}
    if link_path is not None:
        body["link_path"] = link_path
    r = await client.post(f"/api/manuscripts/{mid}/bundle", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["layout"] == "bundle"
    if link_path:
        # ``Path.resolve`` is sync but the test fixture spins it up before
        # the request — keep it on a worker thread to satisfy ASYNC240.
        import asyncio as _asyncio

        resolved = await _asyncio.to_thread(lambda p: str(Path(p).resolve()), link_path)
        assert payload["bundle_link_path"] == resolved
    else:
        assert payload["bundle_link_path"] is None
    return mid


async def test_convert_to_bundle_then_empty_tree(client):
    mid = await _create_bundle(client)
    r = await client.get(f"/api/manuscripts/{mid}/tree")
    assert r.status_code == 200
    payload = r.json()
    assert payload["manuscript_id"] == mid
    assert payload["layout"] == "bundle"
    assert payload["link_mode"] is False
    assert payload["file_count"] == 0
    assert payload["files"] == []


async def test_convert_to_bundle_with_invalid_link_path_400(client):
    create = await client.post("/api/manuscripts", json={"title": "x"})
    mid = create.json()["manuscript"]["id"]
    r = await client.post(
        f"/api/manuscripts/{mid}/bundle",
        json={"link_path": "/this/path/definitely/does/not/exist/xyz123"},
    )
    assert r.status_code == 400


async def test_write_read_delete_text_file(client):
    mid = await _create_bundle(client)

    write = await client.put(
        f"/api/manuscripts/{mid}/files/sections/intro.tex",
        json={"content": "Hello \\LaTeX"},
    )
    assert write.status_code == 200, write.text
    meta = write.json()
    assert meta["path"] == "sections/intro.tex"
    assert meta["is_text"] is True

    tree = (await client.get(f"/api/manuscripts/{mid}/tree")).json()
    assert tree["file_count"] == 1
    assert tree["files"][0]["path"] == "sections/intro.tex"

    read = await client.get(f"/api/manuscripts/{mid}/files/sections/intro.tex")
    assert read.status_code == 200
    body = read.json()
    assert body["encoding"] == "utf-8"
    assert body["content"] == "Hello \\LaTeX"
    assert body["file"]["mime"] in {"text/plain", "application/x-tex", "text/x-tex"}

    rm = await client.delete(f"/api/manuscripts/{mid}/files/sections/intro.tex")
    assert rm.status_code == 204
    assert (await client.get(f"/api/manuscripts/{mid}/tree")).json()["file_count"] == 0


async def test_upload_binary_inlined_as_base64(client):
    mid = await _create_bundle(client)
    payload = b"\x00\x01\x02fake png bytes"
    files = {"file": ("figures/diagram.png", payload, "image/png")}
    up = await client.post(f"/api/manuscripts/{mid}/files/figures/diagram.png", files=files)
    assert up.status_code == 201, up.text

    read = await client.get(f"/api/manuscripts/{mid}/files/figures/diagram.png")
    assert read.status_code == 200
    body = read.json()
    assert body["encoding"] == "base64"
    assert base64.b64decode(body["content"]) == payload
    assert body["file"]["is_text"] is False


async def test_path_traversal_rejected(client):
    """Defence-in-depth: Starlette + httpx normalise `..` out of the URL
    before our handler ever sees it (resulting in 404 / 405). For paths
    that would survive transport (e.g. encoded via the JSON body of a
    future endpoint), :class:`BundleStorage._safe_resolve` still refuses
    with `ManuscriptPathInvalid`. We assert the URL form here; the
    storage-level guard is covered by the unit suite.
    """
    mid = await _create_bundle(client)
    bad = await client.put(
        f"/api/manuscripts/{mid}/files/../../escape.txt",
        json={"content": "x"},
    )
    assert bad.status_code in {400, 404, 405}, bad.text


async def test_tree_on_single_layout_returns_409(client):
    create = await client.post("/api/manuscripts", json={"title": "single"})
    mid = create.json()["manuscript"]["id"]
    r = await client.get(f"/api/manuscripts/{mid}/tree")
    assert r.status_code == 409


async def test_link_mode_lists_existing_user_dir(client, tmp_path):
    # Stand up a tiny fake "paper-dataagent-eval" style folder.
    user_dir = tmp_path / "user_paper"
    (user_dir / "overleaf" / "sections").mkdir(parents=True)
    (user_dir / "overleaf" / "main.tex").write_text("\\documentclass{article}\n")
    (user_dir / "overleaf" / "sections" / "intro.tex").write_text("Intro")
    (user_dir / "design.md").write_text("# Design")

    mid = await _create_bundle(client, link_path=str(user_dir))
    tree = (await client.get(f"/api/manuscripts/{mid}/tree")).json()
    assert tree["link_mode"] is True
    paths = sorted(f["path"] for f in tree["files"])
    assert paths == [
        "design.md",
        "overleaf/main.tex",
        "overleaf/sections/intro.tex",
    ]


async def test_delete_owned_bundle_cleans_disk(client, tmp_path):
    mid = await _create_bundle(client)
    await client.put(
        f"/api/manuscripts/{mid}/files/main.tex",
        json={"content": "body"},
    )
    expected_dir = tmp_path / "manuscripts" / mid
    assert expected_dir.exists()

    r = await client.delete(f"/api/manuscripts/{mid}")
    assert r.status_code == 204
    assert not expected_dir.exists()


# ---------------------------------------------------------------------------
# P7 Phase B — Import / Export
# ---------------------------------------------------------------------------


def _make_paper_dataagent_eval_fixture(root: Path) -> None:
    """Build a tiny clone of the user's `paper-dataagent-eval` shape."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "design.md").write_text("# Design\n\nContent.")
    (root / "overleaf").mkdir()
    (root / "overleaf" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}Body\\end{document}"
    )
    (root / "overleaf" / "references.bib").write_text("@article{x, title={X}}\n")
    (root / "overleaf" / "sections").mkdir()
    (root / "overleaf" / "sections" / "intro.tex").write_text("Intro section")
    (root / "overleaf" / "figures").mkdir()
    (root / "plan").mkdir()
    (root / "plan" / "outline.md").write_text("# Outline")
    (root / "experiments").mkdir()
    (root / "experiments" / "README.md").write_text("# Experiments")
    # Ignored in default listings but should not appear in copy either.
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")


async def test_import_folder_copy_mode(client, tmp_path):
    src = tmp_path / "incoming_paper"
    _make_paper_dataagent_eval_fixture(src)

    r = await client.post(
        "/api/manuscripts/import-folder",
        json={
            "local_path": str(src),
            "mode": "copy",
            "title": "DataAgent eval",
        },
    )
    assert r.status_code == 201, r.text
    record = r.json()
    mid = record["id"]
    assert record["layout"] == "bundle"
    assert record["bundle_link_path"] is None
    assert record["title"] == "DataAgent eval"
    assert record["meta"]["import_mode"] == "copy"

    tree = (await client.get(f"/api/manuscripts/{mid}/tree")).json()
    paths = {f["path"] for f in tree["files"]}
    assert paths == {
        "design.md",
        "overleaf/main.tex",
        "overleaf/references.bib",
        "overleaf/sections/intro.tex",
        "plan/outline.md",
        "experiments/README.md",
    }

    # Mutating the original after copy must NOT affect AAF (true copy).
    (src / "design.md").write_text("UPSTREAM EDIT")
    body = (await client.get(f"/api/manuscripts/{mid}/files/design.md")).json()
    assert "UPSTREAM EDIT" not in body["content"]


async def test_import_folder_link_mode(client, tmp_path):
    src = tmp_path / "linked_paper"
    _make_paper_dataagent_eval_fixture(src)

    r = await client.post(
        "/api/manuscripts/import-folder",
        json={"local_path": str(src), "mode": "link"},
    )
    assert r.status_code == 201, r.text
    record = r.json()
    mid = record["id"]
    assert record["layout"] == "bundle"
    assert record["bundle_link_path"] == str(src.resolve())

    # External edit shows up live in link mode.
    (src / "design.md").write_text("LIVE EDIT")
    body = (await client.get(f"/api/manuscripts/{mid}/files/design.md")).json()
    assert body["content"] == "LIVE EDIT"

    # Conversely, write through AAF reaches the user's directory.
    write = await client.put(
        f"/api/manuscripts/{mid}/files/design.md",
        json={"content": "WRITTEN BY AAF"},
    )
    assert write.status_code == 200
    assert (src / "design.md").read_text() == "WRITTEN BY AAF"


async def test_import_folder_bad_path_400(client):
    r = await client.post(
        "/api/manuscripts/import-folder",
        json={"local_path": "/this/really/does/not/exist/zxc987"},
    )
    assert r.status_code == 400


async def test_import_zip_then_export_zip_roundtrip(client, tmp_path):
    # Build a fixture, zip it, upload it, then download and verify.
    import zipfile as _zipfile

    src = tmp_path / "zipped_paper"
    _make_paper_dataagent_eval_fixture(src)
    zip_buf = io.BytesIO()
    with _zipfile.ZipFile(zip_buf, "w") as zf:
        for p in src.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(src).as_posix())
    files = {"file": ("paper.zip", zip_buf.getvalue(), "application/zip")}
    r = await client.post(
        "/api/manuscripts/import-zip",
        files=files,
        data={"title": "ZipPaper"},
    )
    assert r.status_code == 201, r.text
    record = r.json()
    mid = record["id"]
    assert record["title"] == "ZipPaper"

    tree = (await client.get(f"/api/manuscripts/{mid}/tree")).json()
    assert tree["file_count"] >= 6

    # Auto-detected overleaf subdir.
    export = await client.get(f"/api/manuscripts/{mid}/export-zip")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    assert export.headers["x-bundle-subdir"] == "overleaf"
    out_buf = io.BytesIO(export.content)
    with _zipfile.ZipFile(out_buf) as zf:
        names = sorted(zf.namelist())
    assert names == sorted(["main.tex", "references.bib", "sections/intro.tex"])


async def test_export_zip_force_whole_bundle(client, tmp_path):
    src = tmp_path / "paper2"
    _make_paper_dataagent_eval_fixture(src)
    create = await client.post(
        "/api/manuscripts/import-folder",
        json={"local_path": str(src), "mode": "copy", "title": "Whole"},
    )
    mid = create.json()["id"]

    export = await client.get(f"/api/manuscripts/{mid}/export-zip", params={"subdir": "."})
    assert export.headers["x-bundle-subdir"] == ""
    import zipfile as _zipfile

    with _zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        names = set(zf.namelist())
    # Whole-bundle export keeps the overleaf/ prefix.
    assert "overleaf/main.tex" in names
    assert "design.md" in names


async def test_import_zip_zip_slip_rejected(client, tmp_path):
    """A malicious zip with a `..` entry must be refused before write."""
    import zipfile as _zipfile

    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/escape.txt", b"pwned")
    files = {"file": ("bad.zip", buf.getvalue(), "application/zip")}
    r = await client.post("/api/manuscripts/import-zip", files=files)
    assert r.status_code in {400, 422}, r.text


async def test_download_streams_raw_bytes(client, tmp_path):
    src = tmp_path / "dlpaper"
    _make_paper_dataagent_eval_fixture(src)
    create = await client.post(
        "/api/manuscripts/import-folder",
        json={"local_path": str(src), "mode": "copy"},
    )
    mid = create.json()["id"]

    r = await client.get(f"/api/manuscripts/{mid}/download/overleaf/main.tex")
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('filename="main.tex"')
    assert b"\\documentclass{article}" in r.content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_minimal_pdf(text: str) -> bytes:
    """Generate a 1-page PDF containing *text* using pypdf for a self-contained fixture."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # Manually add a content stream that draws the requested text. pypdf's
    # builder doesn't expose a high-level "draw text" API, so do it the
    # PDF-syntax way and let pypdf wrap the rest of the file structure.
    safe = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = b"BT\n/F1 24 Tf\n72 720 Td\n(" + safe.encode("latin-1") + b") Tj\nET\n"
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)

    # Inject a Helvetica resource so the Tf operator resolves.
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    page[NameObject("/MediaBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), FloatObject(612), FloatObject(792)]
    )

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
