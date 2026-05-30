"""Run skill scripts in an isolated subprocess.

Each call:
  1. Creates/uses the task workdir at ``<workdir>/papers/<task_id>/``.
  2. Spawns ``python <script_path>`` with a whitelisted environment,
     cwd set to the task workdir, no network isolation (that is a
     deployment concern, see aaf-deploy).
  3. Streams arguments as a single JSON object on stdin.
  4. Captures stdout (truncated to 32KB with an artifact file on overflow)
     and stderr.
  5. Collects artifact files from ``<task_workdir>/artifacts/``.

Timeouts kill the whole process group. No orphans are left.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

import structlog

from backend.core.errors import SkillExecutionError, SkillNotFound, SkillTimeout

from .invocations import (
    InvocationStatus,
    SkillInvocationStore,
    make_invocation,
    now_seconds,
)
from .types import ExecResult

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_S = 120
STDOUT_MAX_INLINE_BYTES = 32 * 1024

_DEFAULT_ENV_WHITELIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "PYTHONIOENCODING",
)


class SkillExecutor:
    def __init__(
        self,
        *,
        workdir_root: Path,
        default_timeout_s: int = DEFAULT_TIMEOUT_S,
        python_executable: str | None = None,
        extra_env: dict[str, str] | None = None,
        env_whitelist: tuple[str, ...] = _DEFAULT_ENV_WHITELIST,
        invocations: SkillInvocationStore | None = None,
    ) -> None:
        self._workdir_root = Path(workdir_root)
        self._default_timeout_s = default_timeout_s
        self._python = python_executable or sys.executable
        self._extra_env = extra_env or {}
        self._env_whitelist = env_whitelist
        self._invocations = invocations

    def set_invocation_store(self, store: SkillInvocationStore | None) -> None:
        self._invocations = store

    async def run(
        self,
        *,
        script_path: Path,
        args: dict,
        tool_name: str,
        task_id: str,
        timeout_s: int | None = None,
        uses_llm: bool = False,
        dry_run: bool = False,
    ) -> ExecResult:
        if not script_path.exists():  # noqa: ASYNC240 — one cheap stat, no event-loop stall
            raise SkillNotFound(f"script not found: {script_path}", tool_name=tool_name)

        task_workdir = self._ensure_task_workdir(task_id)
        env = self._build_env(task_workdir=task_workdir, task_id=task_id, uses_llm=uses_llm)
        timeout = timeout_s or self._default_timeout_s

        stdin_bytes = json.dumps(args, ensure_ascii=False).encode("utf-8")
        log.info(
            "skill.executor.start",
            tool=tool_name,
            script=str(script_path),
            task_id=task_id,
            timeout=timeout,
            dry_run=dry_run,
        )

        wall_started = now_seconds()
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            self._python,
            str(script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(task_workdir),
            env=env,
            start_new_session=True,  # own process group → we can kill children
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes), timeout=timeout
            )
            timed_out = False
        except TimeoutError:
            _kill_process_group(proc.pid)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                stdout_bytes, stderr_bytes = b"", b""
            timed_out = True
        except Exception as exc:
            _kill_process_group(proc.pid)
            await self._record_invocation(
                tool_name=tool_name,
                task_id=task_id,
                args=args,
                started_at=wall_started,
                duration_ms=(time.monotonic() - start) * 1000.0,
                status="error",
                error=f"subprocess failure: {exc}",
                result_text="",
                dry_run=dry_run,
            )
            raise SkillExecutionError(f"subprocess failure: {exc}", tool_name=tool_name) from exc

        duration_ms = (time.monotonic() - start) * 1000.0

        stdout_text, stdout_path = _truncate_stdout(stdout_bytes, task_workdir / "stdout.txt")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        artifacts = _collect_artifacts(task_workdir / "artifacts")

        result = ExecResult(
            tool_name=tool_name,
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_text,
            stderr=stderr_text,
            stdout_path=stdout_path,
            artifacts=artifacts,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

        if timed_out:
            log.warning(
                "skill.executor.timeout",
                tool=tool_name,
                duration_ms=duration_ms,
                timeout=timeout,
            )
            await self._record_invocation(
                tool_name=tool_name,
                task_id=task_id,
                args=args,
                started_at=wall_started,
                duration_ms=duration_ms,
                status="timeout",
                error=f"exceeded {timeout}s",
                result_text=stderr_text,
                dry_run=dry_run,
            )
            raise SkillTimeout(
                f"tool {tool_name} exceeded {timeout}s",
                tool_name=tool_name,
                duration_ms=duration_ms,
                partial_result=result.model_dump(mode="json"),
            )

        log.info(
            "skill.executor.end",
            tool=tool_name,
            rc=result.returncode,
            duration_ms=duration_ms,
            artifacts=len(artifacts),
        )
        await self._record_invocation(
            tool_name=tool_name,
            task_id=task_id,
            args=args,
            started_at=wall_started,
            duration_ms=duration_ms,
            status="success" if result.ok else "error",
            error="" if result.ok else stderr_text,
            result_text=stdout_text,
            dry_run=dry_run,
        )
        return result

    # ---- invocation history -----------------------------------------

    async def _record_invocation(
        self,
        *,
        tool_name: str,
        task_id: str,
        args: dict,
        started_at: float,
        duration_ms: float,
        status: InvocationStatus,
        error: str,
        result_text: str,
        dry_run: bool,
    ) -> None:
        store = self._invocations
        if store is None:
            return
        skill_name, script_name = _split_tool(tool_name)
        if not skill_name:
            # Unknown shape (no `<skill>__<script>`); skip the row rather
            # than recording garbage that can never be queried by name.
            return
        inv = make_invocation(
            skill=skill_name,
            script=script_name,
            tool_name=tool_name,
            task_id=task_id,
            status="dry_run" if dry_run and status == "success" else status,
            started_at=started_at,
            duration_ms=duration_ms,
            args=args,
            result_text=result_text,
            error=error,
        )
        try:
            await store.record(inv)
        except Exception:  # pragma: no cover - never let history block the run
            log.exception("skill.executor.invocation_record_failed", tool=tool_name)

    # ---- helpers --------------------------------------------------

    def _ensure_task_workdir(self, task_id: str) -> Path:
        safe_id = task_id.replace("/", "_") or "default"
        wd = (self._workdir_root / "papers" / safe_id).resolve()
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "artifacts").mkdir(exist_ok=True)
        return wd

    def _build_env(self, *, task_workdir: Path, task_id: str, uses_llm: bool) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in self._env_whitelist:
            v = os.environ.get(key)
            if v is not None:
                env[key] = v
        env["PYTHONIOENCODING"] = "utf-8"
        env["AAF_WORKDIR"] = str(task_workdir)
        env["AAF_TASK_ID"] = task_id
        # LLM endpoint leaks only for scripts that opt in.
        if uses_llm:
            llm_endpoint = self._extra_env.get("AAF_LLM_ENDPOINT")
            if llm_endpoint:
                env["AAF_LLM_ENDPOINT"] = llm_endpoint
        for k, v in self._extra_env.items():
            if k == "AAF_LLM_ENDPOINT" and not uses_llm:
                continue
            env[k] = v
        return env


# ---- module-level helpers ------------------------------------------------


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _truncate_stdout(data: bytes, overflow_path: Path) -> tuple[str, Path | None]:
    if len(data) <= STDOUT_MAX_INLINE_BYTES:
        return data.decode("utf-8", errors="replace"), None
    # keep head + tail inline, dump full to disk
    head = data[: STDOUT_MAX_INLINE_BYTES // 2]
    tail = data[-STDOUT_MAX_INLINE_BYTES // 2 :]
    inline = (
        head.decode("utf-8", errors="replace")
        + f"\n\n... <{len(data) - len(head) - len(tail)} bytes omitted; see {overflow_path}> ...\n\n"
        + tail.decode("utf-8", errors="replace")
    )
    overflow_path.write_bytes(data)
    return inline, overflow_path


def _collect_artifacts(artifacts_dir: Path) -> list[Path]:
    if not artifacts_dir.is_dir():
        return []
    return sorted(p.resolve() for p in artifacts_dir.rglob("*") if p.is_file())


def _split_tool(tool_name: str) -> tuple[str, str]:
    """Decompose ``<skill>__<script>`` → ``(skill, script)``.

    Returns ``("", tool_name)`` if no separator is present so callers can
    decide whether to skip the invocation row.
    """
    if "__" not in tool_name:
        return "", tool_name
    skill, script = tool_name.split("__", 1)
    return skill, script


__all__ = ["DEFAULT_TIMEOUT_S", "SkillExecutor"]
