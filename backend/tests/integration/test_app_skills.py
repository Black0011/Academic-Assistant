"""Integration tests for ``/api/skills`` (M7.2).

Covers the full lifecycle exposed by the router:

* Bootstrap the SkillHost + SkillAdmin against a tmp skills root.
* List / detail / install / disable / enable / reload / dry-run.
* Auth gating: 403 for non-admin when ``auth_disabled`` is false; 200 in
  open mode (default).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.skill_host import SkillHost
from backend.core.skill_host.admin import SkillAdmin
from backend.settings import Settings

SKILL_BODY = """---
name: greeter
description: Sample skill for skills-api integration tests.
domain: meta
triggers:
  - greet
  - say hello
version: "1.0.0"
---

# Greeter

Print a JSON object with a greeting message.
"""

SKILL_SCRIPT = (
    "#!/usr/bin/env python3\n"
    '"""Greet."""\n'
    "\n# aaf:network none\n# aaf:timeout 5\n"
    "import json, os, pathlib, sys\n"
    "args = json.loads(sys.stdin.read() or '{}')\n"
    "name = args.get('name', 'world')\n"
    "sys.stdout.write(json.dumps({'hello': name}))\n"
)


def _payload(name: str = "greeter") -> dict[str, Any]:
    body = SKILL_BODY.replace("name: greeter", f"name: {name}")
    return {
        "name": name,
        "body_md": body,
        "scripts": [{"name": "greet", "content": SKILL_SCRIPT}],
        "overwrite": False,
    }


@pytest.fixture
async def app_state(tmp_path: Path) -> AppState:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    workdir = tmp_path / "wd"
    workdir.mkdir()
    settings = Settings()  # type: ignore[call-arg]
    settings.skills_root = skills_root
    settings.skill_workdir_root = workdir
    settings.skill_dry_run_timeout_s = 5
    host = SkillHost.build(skills_root=skills_root, workdir_root=workdir)
    await host.load()
    admin = SkillAdmin(host)
    return AppState(
        settings=settings,
        skill_host=host,
        skill_admin=admin,
    )


@pytest.fixture
async def client(app_state: AppState) -> AsyncIterator[AsyncClient]:
    app = create_app(state=app_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Read-side
# ---------------------------------------------------------------------------


async def test_empty_root_lists_zero_skills(client: AsyncClient):
    r = await client.get("/api/skills")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["generation"] >= 0


async def test_install_then_list_then_detail(client: AsyncClient):
    r = await client.post("/api/skills", json=_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "greeter"
    assert body["enabled"] is True
    assert "Greeter" in body["body_md"]
    assert any(s["name"] == "greet" for s in body["scripts_detail"])
    # detail must NOT include script source (progressive disclosure)
    for sd in body["scripts_detail"]:
        assert "source" not in sd
        assert sd["size_bytes"] > 0

    r = await client.get("/api/skills")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["enabled"] is True
    assert items[0]["version_hash"].startswith("sha256:")

    r = await client.get("/api/skills/greeter")
    assert r.status_code == 200
    assert r.json()["body_md"] == body["body_md"]


async def test_get_script_source_is_lazy(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    r = await client.get("/api/skills/greeter/scripts/greet")
    assert r.status_code == 200
    payload = r.json()
    assert payload["name"] == "greet"
    assert "import json" in payload["source"]
    assert payload["size_bytes"] > 0


async def test_unknown_skill_returns_404(client: AsyncClient):
    assert (await client.get("/api/skills/no-such")).status_code == 404
    assert (await client.get("/api/skills/no-such/scripts/foo")).status_code == 404


# ---------------------------------------------------------------------------
# P13.B — GET /api/skills/graph
#
# We construct two skills wired by ``compatibility.downstream`` and verify
# the route serialises the right nodes / edges. The single most important
# regression check here is that ``/graph`` does not accidentally route to
# the ``/{name}`` handler (which would 404 "skill 'graph' not found").
# ---------------------------------------------------------------------------


SKILL_WITH_DOWNSTREAM = """---
name: alpha
description: Skill alpha — flows into beta.
domain: writing
triggers:
  - alpha
version: "1.0.0"
compatibility:
  downstream: beta
---

# Alpha
"""

SKILL_WITH_UPSTREAM = """---
name: beta
description: Skill beta — receives alpha's output.
domain: writing
triggers:
  - beta
version: "1.0.0"
compatibility:
  upstream: alpha
---

# Beta
"""


def _payload_with_body(name: str, body: str) -> dict[str, Any]:
    return {
        "name": name,
        "body_md": body,
        "scripts": [{"name": "noop", "content": "# aaf:network none\nprint('ok')\n"}],
        "overwrite": False,
    }


async def test_graph_empty_on_fresh_install(client: AsyncClient):
    r = await client.get("/api/skills/graph")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["dangling"] == []
    assert body["cycles"] == []


async def test_graph_serialises_compat_edges(client: AsyncClient):
    """alpha (downstream: beta) + beta (upstream: alpha) ⇒ one ``both``-declared edge."""
    assert (
        await client.post(
            "/api/skills",
            json=_payload_with_body("alpha", SKILL_WITH_DOWNSTREAM),
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/skills",
            json=_payload_with_body("beta", SKILL_WITH_UPSTREAM),
        )
    ).status_code == 201

    r = await client.get("/api/skills/graph")
    assert r.status_code == 200, r.text
    body = r.json()

    names = sorted(n["name"] for n in body["nodes"])
    assert names == ["alpha", "beta"]
    assert len(body["edges"]) == 1
    e = body["edges"][0]
    assert e["source"] == "alpha"
    assert e["target"] == "beta"
    # Both sides declared the same relation — the route must dedupe and
    # mark ``declared_by == "both"``. If this becomes "source" or "target"
    # then the merge logic in ``_build_graph`` regressed.
    assert e["declared_by"] == "both"
    assert body["dangling"] == []
    assert body["cycles"] == []


async def test_graph_route_takes_precedence_over_name_route(client: AsyncClient):
    """Regression guard: a stray skill named "graph" must not shadow the route.

    ``/api/skills/graph`` must always return the graph schema, never a
    ``SkillDetail``. Doing this check in addition to a successful empty
    fetch ensures the routing order (``/graph`` before ``/{name}``) is
    preserved across future router edits.
    """
    r = await client.get("/api/skills/graph")
    assert r.status_code == 200
    body = r.json()
    # SkillDetail does not have a ``nodes`` field. SkillGraphResponse does.
    assert "nodes" in body
    assert "body_md" not in body


# ---------------------------------------------------------------------------
# Mutating endpoints in open mode (auth_disabled=true)
# ---------------------------------------------------------------------------


async def test_install_rejects_duplicate_without_overwrite(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    r = await client.post("/api/skills", json=_payload())
    assert r.status_code == 409


async def test_disable_then_enable_round_trip(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    r = await client.delete("/api/skills/greeter")
    assert r.status_code == 204

    items = (await client.get("/api/skills")).json()["items"]
    by_name = {it["name"]: it for it in items}
    assert by_name["greeter"]["enabled"] is False

    r = await client.post("/api/skills/greeter:enable")
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    items = (await client.get("/api/skills")).json()["items"]
    assert items[0]["enabled"] is True


async def test_disable_alias_idempotent(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    assert (await client.post("/api/skills/greeter:disable")).status_code == 200
    # second call: still returns 200 because disable() is idempotent
    assert (await client.post("/api/skills/greeter:disable")).status_code == 200


async def test_reload_returns_generation_marker(client: AsyncClient):
    r0 = (await client.get("/api/skills")).json()["generation"]
    await client.post("/api/skills", json=_payload())
    r1 = (await client.get("/api/skills")).json()["generation"]
    assert r1 > r0
    r = await client.post("/api/skills/greeter:reload")
    assert r.status_code == 200
    assert r.json()["generation"] >= r1


async def test_patch_replaces_body(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    new = _payload()
    new["body_md"] = new["body_md"].replace(
        "Print a JSON object with a greeting message.",
        "Print a customised greeting payload.",
    )
    r = await client.patch("/api/skills/greeter", json=new)
    assert r.status_code == 200, r.text
    assert "customised" in r.json()["body_md"]


async def test_invocations_history_visible_after_dry_run(client: AsyncClient):
    await client.post("/api/skills", json=_payload())
    r = await client.post(
        "/api/skills/greeter/scripts/greet:dry_run",
        json={"name": "ada"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = await client.get("/api/skills/greeter/invocations")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "dry_run"
    assert items[0]["script"] == "greet"


async def test_validation_error_returns_400(client: AsyncClient):
    bad = _payload(name="Bad Name!")
    r = await client.post("/api/skills", json=bad)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Auth gating (auth_disabled=false → admin required)
# ---------------------------------------------------------------------------


@pytest.fixture
async def secured_state(tmp_path: Path) -> AppState:
    """A second app instance with auth turned on; no users registered."""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    workdir = tmp_path / "wd"
    workdir.mkdir()
    settings = Settings()  # type: ignore[call-arg]
    settings.skills_root = skills_root
    settings.skill_workdir_root = workdir
    settings.auth_disabled = False
    host = SkillHost.build(skills_root=skills_root, workdir_root=workdir)
    await host.load()
    admin = SkillAdmin(host)
    return AppState(settings=settings, skill_host=host, skill_admin=admin)


async def test_unauthenticated_writes_are_rejected(secured_state: AppState):
    app = create_app(state=secured_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post("/api/skills", json=_payload())
        # current_user raises 401 without a bearer token; the gate still
        # treats it as "not admin", so 401 is what surfaces.
        assert r.status_code in {401, 403}


# ---------------------------------------------------------------------------
# P14.C — POST /api/skills/{name}:edges
# ---------------------------------------------------------------------------


async def _install_pair(client: AsyncClient) -> None:
    """Install ``alpha`` (downstream: beta) + ``beta`` (upstream: alpha)
    so we have something to push edges around in."""
    assert (
        await client.post(
            "/api/skills",
            json=_payload_with_body("alpha", SKILL_WITH_DOWNSTREAM),
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/skills",
            json=_payload_with_body("beta", SKILL_WITH_UPSTREAM),
        )
    ).status_code == 201


async def test_edges_endpoint_adds_downstream_edge(client: AsyncClient):
    """Wire alpha → gamma (a brand new edge); the graph view must reflect it."""
    await _install_pair(client)
    # Install a third skill so adding an edge to it isn't dangling.
    await client.post(
        "/api/skills",
        json=_payload_with_body(
            "gamma",
            SKILL_WITH_DOWNSTREAM.replace("name: alpha", "name: gamma")
            .replace("downstream: beta", "downstream: alpha"),
        ),
    )

    r = await client.post(
        "/api/skills/alpha:edges",
        json={"add": [{"kind": "downstream", "target": "gamma"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == [["downstream", "gamma"]]
    # The body_md field returned by the route must reflect the edit.
    assert "gamma" in body["body_md"]

    graph = (await client.get("/api/skills/graph")).json()
    edge_pairs = {(e["source"], e["target"]) for e in graph["edges"]}
    assert ("alpha", "gamma") in edge_pairs


async def test_edges_endpoint_removes_an_edge(client: AsyncClient):
    """Drop alpha → beta; the graph must lose that edge."""
    await _install_pair(client)
    pre = (await client.get("/api/skills/graph")).json()
    assert any(
        e["source"] == "alpha" and e["target"] == "beta" for e in pre["edges"]
    )

    r = await client.post(
        "/api/skills/alpha:edges",
        json={"remove": [{"kind": "downstream", "target": "beta"}]},
    )
    assert r.status_code == 200
    assert r.json()["removed"] == [["downstream", "beta"]]

    post = (await client.get("/api/skills/graph")).json()
    # alpha's side is gone but beta still declares "upstream: alpha", so
    # the edge still exists declared by target only. This pins the
    # frontend's responsibility: deleting a "both"-declared edge needs
    # TWO calls — one to each side.
    edges = [(e["source"], e["target"], e["declared_by"]) for e in post["edges"]]
    assert ("alpha", "beta", "target") in edges


async def test_edges_endpoint_two_calls_remove_both_sides(client: AsyncClient):
    """Demonstrate the documented two-call pattern for a fully-declared edge."""
    await _install_pair(client)
    await client.post(
        "/api/skills/alpha:edges",
        json={"remove": [{"kind": "downstream", "target": "beta"}]},
    )
    await client.post(
        "/api/skills/beta:edges",
        json={"remove": [{"kind": "upstream", "target": "alpha"}]},
    )
    graph = (await client.get("/api/skills/graph")).json()
    assert all(
        not (e["source"] == "alpha" and e["target"] == "beta")
        for e in graph["edges"]
    )


async def test_edges_endpoint_400_on_empty_payload(client: AsyncClient):
    await _install_pair(client)
    r = await client.post("/api/skills/alpha:edges", json={})
    assert r.status_code == 400


async def test_edges_endpoint_404_for_unknown_skill(client: AsyncClient):
    r = await client.post(
        "/api/skills/does-not-exist:edges",
        json={"add": [{"kind": "downstream", "target": "alpha"}]},
    )
    assert r.status_code == 404


async def test_edges_endpoint_400_on_self_reference(client: AsyncClient):
    await _install_pair(client)
    r = await client.post(
        "/api/skills/alpha:edges",
        json={"add": [{"kind": "downstream", "target": "alpha"}]},
    )
    assert r.status_code == 400


async def test_edges_endpoint_does_not_touch_body(client: AsyncClient):
    """The edit must ONLY rewrite frontmatter; the body section must
    survive byte-for-byte. Critical guarantee — otherwise the graph UI
    silently mangles SKILL.md content."""
    await _install_pair(client)
    pre_detail = (await client.get("/api/skills/alpha")).json()
    pre_body = pre_detail["body_md"]
    pre_after_fm = pre_body.split("---", 2)[-1]  # stuff after the second ---

    await client.post(
        "/api/skills/alpha:edges",
        json={"add": [{"kind": "upstream", "target": "beta"}]},
    )
    post_detail = (await client.get("/api/skills/alpha")).json()
    post_after_fm = post_detail["body_md"].split("---", 2)[-1]
    assert post_after_fm == pre_after_fm
