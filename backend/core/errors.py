"""AAF exception hierarchy.

Every non-builtin error raised inside AAF inherits from `AAFError`. The FastAPI
layer maps each subclass to an HTTP status via `backend/api/errors.py`.

Rules (enforced by rule aaf-python-style):
  - Never raise bare `Exception`.
  - Adapters/providers catch vendor-specific exceptions and re-raise one of
    the canonical subclasses here.
  - Callers can introspect `retryable` to decide whether to retry.
"""

from __future__ import annotations

from typing import Any


class AAFError(Exception):
    """Base for all AAF exceptions.

    Attributes
    ----------
    code        : stable machine-readable identifier (e.g. "llm.timeout")
    http_status : default HTTP status when surfaced to the API layer
    retryable   : hint for retry middleware / agents
    context     : free-form key/value details safe to log
    """

    code: str = "aaf.internal_error"
    http_status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
        retryable: bool | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        if retryable is not None:
            self.retryable = retryable
        self.context: dict[str, Any] = context

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "context": self.context,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={str(self)!r})"


class ConfigError(AAFError):
    code = "aaf.config_error"
    http_status = 500


class NotFoundError(AAFError):
    code = "aaf.not_found"
    http_status = 404


class ValidationError(AAFError):
    code = "aaf.validation_error"
    http_status = 422


class AuthError(AAFError):
    code = "aaf.auth_error"
    http_status = 401


class PermissionError(AAFError):
    code = "aaf.permission_error"
    http_status = 403


class ConflictError(AAFError):
    code = "aaf.conflict"
    http_status = 409


class BudgetExceededError(AAFError):
    code = "aaf.budget_exceeded"
    http_status = 402


class LLMError(AAFError):
    """Base for LLM adapter errors."""

    code = "llm.error"
    http_status = 502
    retryable = True


class LLMTimeout(LLMError):
    code = "llm.timeout"
    http_status = 504
    retryable = True


class LLMRateLimit(LLMError):
    code = "llm.rate_limit"
    http_status = 429
    retryable = True

    def __init__(
        self, message: str | None = None, *, retry_after_s: float | None = None, **kw: Any
    ) -> None:
        super().__init__(message, retry_after_s=retry_after_s, **kw)
        self.retry_after_s = retry_after_s


class LLMAuthError(LLMError):
    code = "llm.auth_error"
    http_status = 401
    retryable = False


class LLMContextWindowError(LLMError):
    code = "llm.context_window"
    http_status = 422
    retryable = False


class LLMAPIError(LLMError):
    code = "llm.api_error"
    http_status = 502
    retryable = True


class LLMStreamError(LLMError):
    code = "llm.stream_error"
    http_status = 502
    retryable = True


class SkillError(AAFError):
    code = "skill.error"


class SkillNotFound(SkillError, NotFoundError):
    code = "skill.not_found"


class SkillExecutionError(SkillError):
    code = "skill.execution_error"
    http_status = 500


class SkillTimeout(SkillError):
    code = "skill.timeout"
    http_status = 504
    retryable = True


class MemoryError(AAFError):
    code = "memory.error"


class MemoryNotFound(MemoryError, NotFoundError):
    code = "memory.not_found"


class WorkflowError(AAFError):
    code = "workflow.error"


class WorkflowCancelled(WorkflowError):
    code = "workflow.cancelled"
    http_status = 499


class InfrastructureError(AAFError):
    """Stdlib-level failures (OSError / EnvironmentError) that escaped the
    adapter / store layer.

    Examples that should normalise here:
      * `BrokenPipeError` from an LLM stream whose socket was reset mid-flight
        without first being caught + re-raised by the provider adapter.
      * `ConnectionResetError` from a Chroma RPC.
      * `IsADirectoryError` from a manuscript file IO race.

    These usually indicate **upstream / environmental** problems, not a bug in
    AAF logic, so the default HTTP mapping is 502 (matches ``LLMAPIError``)
    and ``retryable`` is True. ``source_type`` records the original exception
    class name so observability tools can group by the *real* root cause.
    """

    code = "aaf.infrastructure_error"
    http_status = 502
    retryable = True

    def __init__(
        self,
        message: str | None = None,
        *,
        source_type: str | None = None,
        **context: Any,
    ) -> None:
        super().__init__(message, **context)
        self.source_type = source_type or "OSError"


# ---------------------------------------------------------------------------
# Manuscripts (P7 — bundle layout)
# ---------------------------------------------------------------------------


class ManuscriptError(AAFError):
    """Base for manuscript-subsystem errors."""

    code = "manuscript.error"


class ManuscriptNotFound(ManuscriptError, NotFoundError):
    code = "manuscript.not_found"


class ManuscriptLayoutMismatch(ManuscriptError, ValidationError):
    """Operation only valid for one layout (single | bundle) but caller used the other."""

    code = "manuscript.layout_mismatch"


class ManuscriptPathInvalid(ManuscriptError, ValidationError):
    """Requested path tries to escape the bundle root, is absolute, or empty."""

    code = "manuscript.path_invalid"
    http_status = 400


class ManuscriptFileTooLarge(ManuscriptError):
    """Attempted to write a file larger than the per-file cap."""

    code = "manuscript.file_too_large"
    http_status = 413


class ManuscriptBundleTooLarge(ManuscriptError):
    """Attempted to write a file that would push the bundle over the total cap."""

    code = "manuscript.bundle_too_large"
    http_status = 413


class ManuscriptIOError(ManuscriptError):
    """Underlying filesystem operation failed (permissions, disk, IO)."""

    code = "manuscript.io_error"
    http_status = 500


__all__ = [
    "AAFError",
    "AuthError",
    "BudgetExceededError",
    "ConfigError",
    "ConflictError",
    "InfrastructureError",
    "LLMAPIError",
    "LLMAuthError",
    "LLMContextWindowError",
    "LLMError",
    "LLMRateLimit",
    "LLMStreamError",
    "LLMTimeout",
    "ManuscriptBundleTooLarge",
    "ManuscriptError",
    "ManuscriptFileTooLarge",
    "ManuscriptIOError",
    "ManuscriptLayoutMismatch",
    "ManuscriptNotFound",
    "ManuscriptPathInvalid",
    "MemoryError",
    "MemoryNotFound",
    "NotFoundError",
    "PermissionError",
    "SkillError",
    "SkillExecutionError",
    "SkillNotFound",
    "SkillTimeout",
    "ValidationError",
    "WorkflowCancelled",
    "WorkflowError",
]
