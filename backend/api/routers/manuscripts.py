"""Manuscripts API — upload, version, export academic drafts.

The agent (via Write / Revision workflows) and the user both land here.
Every mutation goes through a :class:`ManuscriptStore`; versions are
append-only.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict

from backend.core.app_state import AppState, get_app_state
from backend.core.errors import (
    ManuscriptBundleTooLarge,
    ManuscriptFileTooLarge,
    ManuscriptIOError,
    ManuscriptLayoutMismatch,
    ManuscriptPathInvalid,
)
from backend.core.text import pdf_to_markdown
from backend.manuscripts import (
    BundleConvertInput,
    BundleManifest,
    BundleStorage,
    CommitVersionInput,
    CreateManuscriptInput,
    ImportFolderInput,
    Manuscript,
    ManuscriptFile,
    ManuscriptKind,
    ManuscriptStatus,
    ManuscriptStore,
    ManuscriptVersion,
    UpdateManuscriptInput,
    WriteFileInput,
)

log = structlog.get_logger(__name__)

MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # 40 MB — matches pdf__parse cap

router = APIRouter(prefix="/api/manuscripts", tags=["manuscripts"])


# ---------------------------------------------------------------------------
# Response envelopes
# ---------------------------------------------------------------------------


class ManuscriptListResponse(BaseModel):
    items: list[Manuscript]
    total: int


class VersionListResponse(BaseModel):
    items: list[ManuscriptVersion]
    total: int


class ManuscriptEnvelope(BaseModel):
    manuscript: Manuscript
    version: ManuscriptVersion | None = None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _require_store(state: AppState) -> ManuscriptStore:
    store = getattr(state, "manuscripts", None)
    if store is None:
        raise HTTPException(status_code=503, detail="manuscripts subsystem not ready")
    return store


def _require_bundle_storage(state: AppState) -> BundleStorage:
    storage = getattr(state, "bundle_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="manuscript bundle storage not ready")
    return storage


async def _get_bundle_or_404(store: ManuscriptStore, manuscript_id: str) -> Manuscript:
    record = await store.get(manuscript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="manuscript not found")
    if record.layout != "bundle":
        raise HTTPException(
            status_code=409,
            detail=(
                "manuscript is single-layout; convert to bundle first via "
                "POST /api/manuscripts/{id}/bundle"
            ),
        )
    return record


def _aaf_to_http(exc: Exception) -> HTTPException:
    """Map a manuscript-domain :class:`AAFError` onto an :class:`HTTPException`.

    Routers raise via this so the JSON body stays uniform and the status code
    matches the error class's declared ``http_status``. We stay close to the
    underlying ``AAFError`` semantics rather than building yet another error
    envelope here.
    """
    if isinstance(exc, ManuscriptPathInvalid):
        return HTTPException(status_code=exc.http_status, detail=str(exc))
    if isinstance(exc, ManuscriptLayoutMismatch):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ManuscriptFileTooLarge | ManuscriptBundleTooLarge):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, ManuscriptIOError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ManuscriptEnvelope,
    status_code=201,
    summary="Create a new manuscript (optionally with initial content)",
)
async def create_manuscript(
    body: CreateManuscriptInput,
    state: AppState = Depends(get_app_state),
) -> ManuscriptEnvelope:
    store = _require_store(state)
    record, version = await store.create(body)
    return ManuscriptEnvelope(manuscript=record, version=version)


@router.get(
    "",
    response_model=ManuscriptListResponse,
    summary="List manuscripts with optional filters",
)
async def list_manuscripts(
    user_id: str | None = Query(None),
    status: ManuscriptStatus | None = Query(None),
    kind: ManuscriptKind | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: AppState = Depends(get_app_state),
) -> ManuscriptListResponse:
    store = _require_store(state)
    items = await store.list(
        user_id=user_id,
        status=status,
        kind=kind,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    return ManuscriptListResponse(items=items, total=len(items))


@router.get("/stats", summary="Manuscript counts by status")
async def stats(state: AppState = Depends(get_app_state)) -> dict:
    store = _require_store(state)
    return await store.stats()


@router.get(
    "/{manuscript_id}",
    response_model=Manuscript,
    summary="Get manuscript metadata",
)
async def get_manuscript(
    manuscript_id: str,
    state: AppState = Depends(get_app_state),
) -> Manuscript:
    store = _require_store(state)
    record = await store.get(manuscript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="manuscript not found")
    return record


@router.patch(
    "/{manuscript_id}",
    response_model=Manuscript,
    summary="Update manuscript metadata (title, status, tags, meta)",
)
async def update_manuscript(
    manuscript_id: str,
    body: UpdateManuscriptInput,
    state: AppState = Depends(get_app_state),
) -> Manuscript:
    store = _require_store(state)
    try:
        return await store.update(manuscript_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="manuscript not found") from exc


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


# ---------------------------------------------------------------------------
# Version endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{manuscript_id}/versions",
    response_model=ManuscriptVersion,
    status_code=201,
    summary="Commit a new version of a manuscript",
)
async def commit_version(
    manuscript_id: str,
    body: CommitVersionInput,
    state: AppState = Depends(get_app_state),
) -> ManuscriptVersion:
    store = _require_store(state)
    try:
        return await store.commit_version(manuscript_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="manuscript not found") from exc


@router.get(
    "/{manuscript_id}/versions",
    response_model=VersionListResponse,
    summary="List versions (newest first)",
)
async def list_versions(
    manuscript_id: str,
    limit: int = Query(50, ge=1, le=500),
    state: AppState = Depends(get_app_state),
) -> VersionListResponse:
    store = _require_store(state)
    try:
        items = await store.list_versions(manuscript_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="manuscript not found") from exc
    return VersionListResponse(items=items, total=len(items))


@router.get(
    "/{manuscript_id}/versions/{version}",
    response_model=ManuscriptVersion,
    summary="Read a specific version's full content",
)
async def get_version(
    manuscript_id: str,
    version: int,
    state: AppState = Depends(get_app_state),
) -> ManuscriptVersion:
    store = _require_store(state)
    record = await store.get_version(manuscript_id, version)
    if record is None:
        raise HTTPException(status_code=404, detail="version not found")
    return record


@router.get(
    "/{manuscript_id}/export",
    summary="Export a manuscript as markdown (latest or a specific version)",
    response_class=Response,
)
async def export_manuscript(
    manuscript_id: str,
    version: int | None = Query(None, ge=1, description="Specific version; defaults to latest."),
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    record = await store.get(manuscript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="manuscript not found")

    target_version = version or record.current_version
    if target_version <= 0:
        raise HTTPException(status_code=404, detail="manuscript has no versions")
    snapshot = await store.get_version(manuscript_id, target_version)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="version not found")

    header = (
        f"---\n"
        f"title: {record.title or manuscript_id}\n"
        f"manuscript_id: {manuscript_id}\n"
        f"version: {snapshot.version}\n"
        f"status: {record.status}\n"
        f"origin: {snapshot.origin}\n"
        f"---\n\n"
    )
    filename = f"{(record.title or manuscript_id).replace(' ', '_')}_v{snapshot.version}.md"
    return Response(
        content=(header + snapshot.content).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Upload (markdown OR PDF)
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=ManuscriptEnvelope,
    status_code=201,
    summary="Upload a .md / .markdown / .txt / .pdf / .docx file as a new manuscript",
)
async def upload_manuscript(
    file: UploadFile = File(..., description="markdown or PDF file"),
    title: str = Form(""),
    kind: ManuscriptKind = Form("paper"),
    section: str | None = Form(None),
    topic: str | None = Form(None),
    tags: str = Form("", description="comma-separated tags"),
    user_id: str | None = Form(None),
    session_id: str | None = Form(None),
    state: AppState = Depends(get_app_state),
) -> ManuscriptEnvelope:
    store = _require_store(state)

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="empty upload")

    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()

    if filename.endswith(".pdf") or "pdf" in content_type:
        try:
            content, meta_extra = pdf_to_markdown(raw)
        except Exception as exc:
            log.warning("manuscript.pdf_parse_failed", error=str(exc))
            raise HTTPException(status_code=422, detail=f"pdf parse failed: {exc}") from exc
    elif filename.endswith((".md", ".markdown", ".txt")) or "text" in content_type:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="file must be utf-8 text") from exc
        meta_extra = {}
    elif filename.endswith(".docx") or "wordprocessingml" in content_type:
        try:
            from io import BytesIO
            from docx import Document
            doc = Document(BytesIO(raw))
            content = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            if not content:
                raise HTTPException(status_code=422, detail="docx produced no extractable text")
        except Exception as exc:
            log.warning("manuscript.docx_parse_failed", error=str(exc))
            raise HTTPException(status_code=422, detail=f"docx parse failed: {exc}") from exc
        meta_extra = {"format": "docx"}
    else:
        raise HTTPException(status_code=415, detail="unsupported file type; expected .md/.txt/.pdf/.docx")

    if not content.strip():
        raise HTTPException(status_code=422, detail="file produced no extractable text")

    resolved_title = title or (file.filename or "untitled").rsplit(".", 1)[0]
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    meta: dict[str, Any] = {
        "uploaded_filename": file.filename,
        "content_type": file.content_type,
        "bytes": len(raw),
        **meta_extra,
    }

    body = CreateManuscriptInput(
        title=resolved_title,
        kind=kind,
        section=section,
        topic=topic,
        tags=parsed_tags,
        user_id=user_id,
        session_id=session_id,
        meta=meta,
        content=content,
        note=f"uploaded from {file.filename}",
    )
    record, version = await store.create(body)
    # Override origin marker for upload path.
    if version is not None:
        record = await store.update(
            record.id, UpdateManuscriptInput(meta={"origin": "user_upload"})
        )
    return ManuscriptEnvelope(manuscript=record, version=version)


# ---------------------------------------------------------------------------
# Bundle endpoints (P7) — file-tree CRUD on project-shaped manuscripts.
# Routes deliberately use ``/files/{path:path}`` so callers can express
# nested paths like ``overleaf/sections/methodology.tex`` directly. Path
# safety is enforced inside :class:`BundleStorage` — never trust the URL.
# ---------------------------------------------------------------------------


class FileEnvelope(BaseModel):
    """Read response for a single file (text mode).

    Binary payloads stream as ``application/octet-stream`` (see the GET
    handler) — they never travel through this envelope.
    """

    model_config = ConfigDict(extra="forbid")

    file: ManuscriptFile
    encoding: str  # "utf-8" for text, "base64" for binary inlined small files
    content: str


@router.post(
    "/{manuscript_id}/bundle",
    response_model=Manuscript,
    summary=(
        "Promote a manuscript to bundle layout (copy mode if no link_path, link mode otherwise)"
    ),
)
async def convert_to_bundle(
    manuscript_id: str,
    body: BundleConvertInput,
    state: AppState = Depends(get_app_state),
) -> Manuscript:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await store.get(manuscript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="manuscript not found")

    # Validate link path eagerly — we'd rather 400 here than 503 on first
    # tree call. Empty string is treated as "no link" (copy mode). Path
    # resolution + ``stat`` happen in a worker thread (filesystem hit).
    link_path: str | None = (body.link_path or "").strip() or None
    if link_path:

        def _validate(p: str) -> Path:
            return Path(p).expanduser().resolve()

        resolved = await asyncio.to_thread(_validate, link_path)
        is_dir = await asyncio.to_thread(resolved.is_dir)
        if not is_dir:
            raise HTTPException(
                status_code=400,
                detail=f"bundle link_path does not exist or is not a directory: {resolved}",
            )
        link_path = str(resolved)

    updated = await store.update(
        manuscript_id,
        UpdateManuscriptInput(
            layout="bundle",
            bundle_link_path=link_path or "",
            bundle_versioning=body.versioning,
        ),
    )
    # Touch the storage layer so copy-mode bundles get their dir provisioned.
    await storage.init_for(updated)
    log.info(
        "manuscript.bundle.converted",
        manuscript_id=manuscript_id,
        link_mode=link_path is not None,
        link_path=link_path,
    )
    return updated


@router.get(
    "/{manuscript_id}/tree",
    response_model=BundleManifest,
    summary="List every file in the bundle (flat)",
)
async def get_bundle_tree(
    manuscript_id: str,
    include_hash: bool = Query(False, description="Compute SHA-256 per file (slower)."),
    include_hidden: bool = Query(False, description="Include dotfiles + .git etc."),
    with_content: bool = Query(False, description="Embed content for small text files."),
    max_content_size: int = Query(50000, description="Max bytes for embedded content."),
    state: AppState = Depends(get_app_state),
) -> BundleManifest:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    try:
        manifest = await storage.list_tree(
            record, include_hash=include_hash, include_hidden=include_hidden
        )
        if with_content:
            for f in manifest.files:
                if f.is_text and f.size <= max_content_size:
                    try:
                        content = await storage.read_text(record, f.path)
                        f.content = content
                    except Exception:
                        f.content = None
        return manifest
    except ManuscriptPathInvalid as exc:
        raise _aaf_to_http(exc) from exc


@router.get(
    "/{manuscript_id}/files/{file_path:path}",
    summary="Read one file (text → JSON envelope, binary → octet-stream).",
)
async def read_bundle_file(
    manuscript_id: str,
    file_path: str,
    text: bool = Query(
        True,
        description=(
            "When true (default), text-detected files come back as a JSON "
            "envelope with utf-8 content. Set false to always stream raw bytes."
        ),
    ),
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)

    try:
        meta = await storage.stat(record, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except ManuscriptPathInvalid as exc:
        raise _aaf_to_http(exc) from exc

    if text and meta.is_text and meta.size <= storage.max_file_bytes:
        try:
            content = await storage.read_text(record, file_path)
        except ManuscriptPathInvalid as exc:
            # Encoding mismatch: fall through to a binary stream below.
            log.info(
                "manuscript.bundle.fallback_binary",
                manuscript_id=manuscript_id,
                path=file_path,
                reason=str(exc),
            )
        else:
            envelope = FileEnvelope(file=meta, encoding="utf-8", content=content)
            return Response(
                content=envelope.model_dump_json(),
                media_type="application/json",
            )

    # Binary path: inline small payloads as base64 in the same envelope so
    # the frontend doesn't need a separate request. Larger payloads should
    # use the dedicated download endpoint (Phase B).
    try:
        raw = await storage.read_bytes(record, file_path)
    except ManuscriptPathInvalid as exc:
        raise _aaf_to_http(exc) from exc
    envelope = FileEnvelope(
        file=meta,
        encoding="base64",
        content=base64.b64encode(raw).decode("ascii"),
    )
    return Response(
        content=envelope.model_dump_json(),
        media_type="application/json",
    )


@router.put(
    "/{manuscript_id}/files/{file_path:path}",
    response_model=ManuscriptFile,
    summary="Create or overwrite a text file (UTF-8). Use multipart upload for binary.",
)
async def write_bundle_text_file(
    manuscript_id: str,
    file_path: str,
    body: WriteFileInput,
    state: AppState = Depends(get_app_state),
) -> ManuscriptFile:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    try:
        return await storage.write_text(record, file_path, body.content, body.encoding)
    except (
        ManuscriptPathInvalid,
        ManuscriptFileTooLarge,
        ManuscriptBundleTooLarge,
        ManuscriptIOError,
    ) as exc:
        raise _aaf_to_http(exc) from exc


@router.post(
    "/{manuscript_id}/files/{file_path:path}",
    response_model=ManuscriptFile,
    status_code=201,
    summary="Upload a binary file (multipart). Overwrites if the path exists.",
)
async def upload_bundle_binary_file(
    manuscript_id: str,
    file_path: str,
    file: UploadFile = File(..., description="any binary or text content"),
    state: AppState = Depends(get_app_state),
) -> ManuscriptFile:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    raw = await file.read()
    try:
        return await storage.write_bytes(record, file_path, raw)
    except (
        ManuscriptPathInvalid,
        ManuscriptFileTooLarge,
        ManuscriptBundleTooLarge,
        ManuscriptIOError,
    ) as exc:
        raise _aaf_to_http(exc) from exc


@router.delete(
    "/{manuscript_id}/files/{file_path:path}",
    status_code=204,
    summary="Delete one file (or empty directory) from the bundle.",
)
async def delete_bundle_file(
    manuscript_id: str,
    file_path: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    try:
        existed = await storage.delete_path(record, file_path)
    except (ManuscriptPathInvalid, ManuscriptIOError) as exc:
        raise _aaf_to_http(exc) from exc
    if not existed:
        raise HTTPException(status_code=404, detail="file not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Bundle import — folder + zip (P7 Phase B).
# Both create a fresh manuscript and immediately populate it. Importing
# into an existing manuscript happens through the file CRUD above.
# ---------------------------------------------------------------------------


@router.post(
    "/import-folder",
    response_model=Manuscript,
    status_code=201,
    summary=(
        "Create a bundle manuscript from a local directory "
        "(copy the tree into AAF, or link to it in place)."
    ),
)
async def import_folder(
    body: ImportFolderInput,
    state: AppState = Depends(get_app_state),
) -> Manuscript:
    store = _require_store(state)
    storage = _require_bundle_storage(state)

    def _resolve(p: str) -> Path:
        return Path(p).expanduser().resolve()

    source = await asyncio.to_thread(_resolve, body.local_path)
    is_dir = await asyncio.to_thread(source.is_dir)
    if not is_dir:
        raise HTTPException(
            status_code=400,
            detail=f"local_path does not exist or is not a directory: {source}",
        )

    title = body.title or source.name

    create_body = CreateManuscriptInput(
        title=title,
        kind=body.kind,
        layout="bundle",
        bundle_link_path=str(source) if body.mode == "link" else None,
        bundle_versioning=body.mode == "copy",
        user_id=body.user_id,
        session_id=body.session_id,
        meta={"imported_from": str(source), "import_mode": body.mode},
    )
    record, _ = await store.create(create_body)

    if body.mode == "copy":
        try:
            await storage.import_directory(record, source, overwrite=body.overwrite)
        except (
            ManuscriptPathInvalid,
            ManuscriptFileTooLarge,
            ManuscriptBundleTooLarge,
            ManuscriptIOError,
        ) as exc:
            await store.delete(record.id)
            raise _aaf_to_http(exc) from exc
    else:
        # Link mode just needs the directory to already exist (it's where we
        # already are pointing). Touching init_for validates that.
        try:
            await storage.init_for(record)
        except ManuscriptPathInvalid as exc:
            await store.delete(record.id)
            raise _aaf_to_http(exc) from exc

    log.info(
        "manuscript.import_folder",
        manuscript_id=record.id,
        source=str(source),
        mode=body.mode,
    )
    final = await store.get(record.id)
    assert final is not None
    return final


@router.post(
    "/import-zip",
    response_model=Manuscript,
    status_code=201,
    summary="Create a bundle manuscript from an uploaded .zip archive.",
)
async def import_zip(
    file: UploadFile = File(..., description=".zip archive of a paper project"),
    title: str = Form(""),
    kind: ManuscriptKind = Form("paper"),
    overwrite: bool = Form(False),
    user_id: str | None = Form(None),
    session_id: str | None = Form(None),
    state: AppState = Depends(get_app_state),
) -> Manuscript:
    store = _require_store(state)
    storage = _require_bundle_storage(state)

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(raw) > storage.max_bundle_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"zip exceeds bundle cap ({storage.max_bundle_bytes // (1024 * 1024)}MB) "
                "before extraction"
            ),
        )

    inferred_title = title or (file.filename or "untitled").rsplit(".", 1)[0]
    create_body = CreateManuscriptInput(
        title=inferred_title,
        kind=kind,
        layout="bundle",
        user_id=user_id,
        session_id=session_id,
        meta={"imported_from": file.filename or "upload.zip", "import_mode": "zip"},
    )
    record, _ = await store.create(create_body)
    try:
        await storage.import_zip(record, raw, overwrite=overwrite)
    except (
        ManuscriptPathInvalid,
        ManuscriptFileTooLarge,
        ManuscriptBundleTooLarge,
        ManuscriptIOError,
    ) as exc:
        await store.delete(record.id)
        raise _aaf_to_http(exc) from exc

    log.info(
        "manuscript.import_zip",
        manuscript_id=record.id,
        filename=file.filename,
        bytes=len(raw),
    )
    final = await store.get(record.id)
    assert final is not None
    return final


# ---------------------------------------------------------------------------
# Bundle export — zip the whole project, or just the Overleaf subdir.
# ---------------------------------------------------------------------------


@router.get(
    "/{manuscript_id}/export-zip",
    summary="Download a zip of the bundle (auto-picks overleaf/ subdir if present).",
    response_class=Response,
)
async def export_bundle_zip(
    manuscript_id: str,
    subdir: str | None = Query(
        None,
        description=(
            "Pack only this subdirectory of the bundle. Empty / unset triggers "
            "auto-detection — if `overleaf/` exists at the root, it's used; "
            "otherwise the whole bundle is packed. Pass `subdir=.` to force the "
            "whole bundle."
        ),
    ),
    include_hidden: bool = Query(False, description="Include dotfiles + .git/."),
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)

    if subdir == ".":
        chosen: str | None = None
    elif subdir is None or subdir == "":
        chosen = await asyncio.to_thread(storage.detect_overleaf_subdir, record)
    else:
        chosen = subdir

    try:
        zip_bytes = await asyncio.to_thread(
            storage.export_zip, record, subdir=chosen, include_hidden=include_hidden
        )
    except (ManuscriptPathInvalid, ManuscriptLayoutMismatch) as exc:
        raise _aaf_to_http(exc) from exc

    base = (record.title or manuscript_id).replace(" ", "_") or manuscript_id
    suffix = f"_{chosen}" if chosen else ""
    filename = f"{base}{suffix}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Bundle-Subdir": chosen or "",
        },
    )


@router.get(
    "/{manuscript_id}/download/{file_path:path}",
    summary="Stream-download a single bundle file as raw bytes.",
    response_class=Response,
)
async def download_bundle_file(
    manuscript_id: str,
    file_path: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    storage = _require_bundle_storage(state)
    record = await _get_bundle_or_404(store, manuscript_id)
    try:
        meta = await storage.stat(record, file_path)
        raw = await storage.read_bytes(record, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except ManuscriptPathInvalid as exc:
        raise _aaf_to_http(exc) from exc

    name = file_path.rsplit("/", 1)[-1]
    return Response(
        content=raw,
        media_type=meta.mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


__all__ = ["router"]
