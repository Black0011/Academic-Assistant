"""Workflow registry — explicit registration + package auto-discovery.

Two registration paths:

* **Decorator / explicit** — import any `BaseWorkflow` subclass and pass it
  to :meth:`WorkflowRegistry.register`. Used by tests and by third-party
  plugins that don't want filesystem scanning.
* **Discovery** — call :meth:`WorkflowRegistry.discover` once at app
  boot. It walks the ``backend.workflows`` package, imports each
  submodule, and registers every concrete ``BaseWorkflow`` subclass that
  declares a non-empty ``name``.

The registry is deliberately process-local. ARQ workers get their own
fresh registry populated the same way; the router never imports concrete
workflow classes, so adding a workflow is a one-file change.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

import structlog

from backend.core.errors import ConfigError, NotFoundError

from .base import BaseWorkflow

log = structlog.get_logger(__name__)


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, type[BaseWorkflow]] = {}

    # ---- registration ------------------------------------------------

    def register(self, cls: type[BaseWorkflow], *, overwrite: bool = False) -> type[BaseWorkflow]:
        if not cls.name:
            raise ConfigError(
                f"workflow {cls.__name__} has no `name` class attribute — cannot register"
            )
        if cls.name in self._workflows and not overwrite:
            existing = self._workflows[cls.name]
            if existing is cls:
                return cls
            raise ConfigError(
                f"workflow '{cls.name}' already registered as "
                f"{existing.__module__}.{existing.__name__}"
            )
        self._workflows[cls.name] = cls
        return cls

    def unregister(self, name: str) -> None:
        self._workflows.pop(name, None)

    # ---- lookup ------------------------------------------------------

    def has(self, name: str) -> bool:
        return name in self._workflows

    def get(self, name: str) -> type[BaseWorkflow]:
        cls = self._workflows.get(name)
        if cls is None:
            raise NotFoundError(f"workflow '{name}' not registered", available=self.names())
        return cls

    def instantiate(self, name: str) -> BaseWorkflow:
        """Return a fresh workflow instance for a single run."""
        return self.get(name)()

    def names(self) -> list[str]:
        return sorted(self._workflows)

    def describe(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for name in self.names():
            cls = self._workflows[name]
            out.append(
                {
                    "name": name,
                    "version": getattr(cls, "version", "1.0.0"),
                    "module": cls.__module__,
                    "class": cls.__name__,
                    "doc": (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else "",
                }
            )
        return out

    # ---- discovery ---------------------------------------------------

    def discover(self, package: str = "backend.workflows") -> int:
        """Import every submodule of *package* and register all non-base
        :class:`BaseWorkflow` subclasses that define a ``name``.

        Idempotent — re-importing modules is a no-op and re-registering
        the same class is silently accepted. Returns the number of
        workflows registered by this call (new additions only).
        """
        pkg = importlib.import_module(package)
        before = len(self._workflows)
        for module_info in _iter_submodules(pkg):
            try:
                importlib.import_module(module_info.name)
            except Exception as exc:
                log.warning(
                    "workflow.discover.import_failed", module=module_info.name, error=str(exc)
                )
                continue
        for cls in _all_subclasses(BaseWorkflow):
            if cls is BaseWorkflow:
                continue
            name = getattr(cls, "name", "") or ""
            if not name:
                continue
            if name in self._workflows and self._workflows[name] is cls:
                continue
            # Silent overwrite during discovery would hide plugin conflicts.
            if name in self._workflows:
                existing = self._workflows[name]
                log.warning(
                    "workflow.discover.name_conflict",
                    name=name,
                    keep=f"{existing.__module__}.{existing.__name__}",
                    skipped=f"{cls.__module__}.{cls.__name__}",
                )
                continue
            self._workflows[name] = cls
        added = len(self._workflows) - before
        log.info("workflow.discover", added=added, total=len(self._workflows))
        return added


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _iter_submodules(pkg: object) -> Iterator[pkgutil.ModuleInfo]:
    path = getattr(pkg, "__path__", None)
    if path is None:
        return iter(())
    return pkgutil.walk_packages(path, prefix=f"{pkg.__name__}.")  # type: ignore[attr-defined]


def _all_subclasses(cls: type) -> list[type]:
    seen: set[type] = set()
    queue: list[type] = list(cls.__subclasses__())
    while queue:
        sub = queue.pop()
        if sub in seen:
            continue
        seen.add(sub)
        queue.extend(sub.__subclasses__())
    return list(seen)


# ---------------------------------------------------------------------------
# Default registry (populated lazily at app startup by `build_default_registry`)
# ---------------------------------------------------------------------------


def build_default_registry() -> WorkflowRegistry:
    reg = WorkflowRegistry()
    reg.discover()
    return reg


__all__ = ["WorkflowRegistry", "build_default_registry"]
