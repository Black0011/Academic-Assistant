"""Liveness / readiness endpoints.

Kept deliberately tiny — no DB round-trip, no LLM ping. These routes are
what an orchestrator (Docker, Kubernetes, systemd) polls; they must stay
cheap and side-effect-free.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.core.app_state import AppState, get_app_state

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/version", summary="Framework version + runtime wiring")
async def version(state: AppState = Depends(get_app_state)) -> dict[str, Any]:
    from backend.app import APP_VERSION
    from backend.core.build_info import BUILD_INFO

    bundle = state.memory
    return {
        "version": APP_VERSION,
        # P12.2 — git-detected identity of the *actually running* process.
        # Lets the frontend show the user which commit they're talking
        # to, so "did my fix actually deploy?" stops being a guess.
        "build": BUILD_INFO.to_dict(),
        "llm_provider": getattr(state.llm, "name", None) if state.llm else None,
        "memory": {
            "vector": type(bundle.vector).__name__ if bundle else None,
            "knowledge": type(bundle.knowledge).__name__ if bundle else None,
            "heuristic": type(bundle.heuristic).__name__ if bundle else None,
            "episodic": type(bundle.episodic).__name__ if bundle else None,
            "session": type(bundle.session).__name__ if bundle else None,
        },
        "tools": state.tools.names() if state.tools else [],
    }
