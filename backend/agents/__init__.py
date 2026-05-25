"""Stateless agents.

Each agent in this package is a small object whose lifetime is bounded
by the runner — they hold no per-task mutable state and are safe to
construct once and reuse across runs.

Currently exported:

* :class:`backend.agents.evolver.EvolverAgent` — turns a successful
  workflow output into a *draft* proposal in the gated-proposal store
  (M8.1). Human review is required before the proposal becomes a
  heuristic — the agent never writes directly to the HeuristicStore.

* :class:`backend.agents.research_agent.ResearchAgent` — LLM-driven
  academic paper search via tool-calling loop.  Plans search strategy,
  translates non-English queries, executes multi-round arXiv searches,
  and collects results.  Falls back to the legacy pipeline when no LLM
  is wired.

The package deliberately mirrors the per-skill / per-workflow naming
discipline: one file per agent, no cross-agent imports inside this
package.
"""

from __future__ import annotations

from .evolver import EvolverAgent
from .research_agent import ResearchAgent

__all__ = ["EvolverAgent", "ResearchAgent"]
