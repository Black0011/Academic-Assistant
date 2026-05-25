from backend.core.errors import (
    AAFError,
    LLMRateLimit,
    LLMTimeout,
    MemoryNotFound,
    NotFoundError,
)


def test_default_attrs():
    e = AAFError("boom", foo="bar")
    assert e.code == "aaf.internal_error"
    assert e.http_status == 500
    assert e.retryable is False
    assert e.context == {"foo": "bar"}
    assert "boom" in str(e)
    d = e.to_dict()
    assert d["type"] == "AAFError"
    assert d["context"] == {"foo": "bar"}


def test_subclass_defaults():
    e = LLMTimeout()
    assert e.code == "llm.timeout"
    assert e.http_status == 504
    assert e.retryable is True


def test_rate_limit_retry_after():
    e = LLMRateLimit("slow down", retry_after_s=2.5)
    assert e.retry_after_s == 2.5
    assert e.context["retry_after_s"] == 2.5


def test_diamond_inheritance():
    """MemoryNotFound is both a MemoryError and NotFoundError."""
    e = MemoryNotFound("card missing", id="p123")
    assert isinstance(e, NotFoundError)
    assert isinstance(e, AAFError)
    assert e.http_status == 404
