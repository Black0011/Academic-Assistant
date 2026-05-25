from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from backend.core.events import Event, EventType


def test_event_is_frozen():
    e = Event(type="x", task_id="t1", data={"a": 1})
    with pytest.raises(FrozenInstanceError):
        e.type = "y"


def test_event_default_timestamp_is_utc_aware():
    e = Event(type="task.start")
    assert isinstance(e.at, datetime)
    assert e.at.tzinfo is not None
    assert e.at.tzinfo.utcoffset(e.at) == UTC.utcoffset(e.at)


def test_event_to_dict_roundtrip():
    e = Event(type="task.start", task_id="t1", data={"x": 2})
    d = e.to_dict()
    assert d["type"] == "task.start"
    assert d["task_id"] == "t1"
    assert d["data"] == {"x": 2}
    # ISO-format timestamp
    datetime.fromisoformat(d["at"])


def test_eventtype_constants_stable():
    for attr in (
        "TASK_START",
        "TASK_END",
        "TASK_ERROR",
        "TASK_RETRY",
        "TASK_STAGE_START",
        "TASK_STAGE_END",
        "SKILL_MATCHED",
        "LLM_CALL",
        "RULE_BLOCK",
    ):
        assert isinstance(getattr(EventType, attr), str)
