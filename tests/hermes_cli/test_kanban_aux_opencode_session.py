"""Kanban aux calls retain OpenCode session affinity (#112043, fork-local complement).

Covers the scoped_runtime_main binding in `_call_aux` (specify/decompose), the
goal-judge path (`judge_goal(task_id=...)`), and the wire-level header emission.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import hermes_cli.goals as goals_mod
from hermes_cli import kanban_decompose as decompose
from hermes_cli import kanban_specify as specify


def _response():
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


@pytest.mark.parametrize("caller", [specify._call_aux, decompose._call_aux])
def test_kanban_aux_call_supplies_stable_opencode_session(caller):
    """Specify and decompose headless calls need a task-stable relay key."""
    from agent import auxiliary_client as aux

    seen = []

    def call_llm(**kwargs):
        seen.append(aux._runtime_main_value("session_id"))
        return _response()

    with patch.object(aux, "call_llm", call_llm):
        reply, reason = caller(
            "specify", "t_123", aux_task="triage_specifier", system="system", user="user",
            max_tokens=100, timeout=10,
        )

    assert (reply, reason) == ("ok", "")
    assert seen == ["kanban:t_123"]

    # The actual wire path: with the scope active, _build_call_kwargs emits the header.
    from agent.auxiliary_client import scoped_runtime_main
    with scoped_runtime_main({"session_id": "kanban:t_123"}):
        kwargs = aux._build_call_kwargs(
            "opencode-go", "glm-5", [{"role": "user", "content": "hi"}],
            base_url="https://opencode.ai/zen/go/v1")
    assert kwargs["extra_headers"]["x-opencode-session"] == "kanban:t_123"


def test_kanban_aux_call_does_not_add_session_for_other_providers():
    """The task binding must remain inert for non-OpenCode auxiliary routes."""
    from agent.opencode_affinity import merge_opencode_session_headers

    seen = []

    def call_llm(**kwargs):
        from agent import auxiliary_client as aux
        seen.append(merge_opencode_session_headers(
            {"extra_headers": {"x-existing": "keep"}}, "openai", None,
            aux._runtime_main_value("session_id"),
        ).get("extra_headers", {}))
        return _response()

    from agent import auxiliary_client as aux
    with patch.object(aux, "call_llm", call_llm):
        reply, reason = specify._call_aux(
            "specify", "t_123", aux_task="triage_specifier", system="system", user="user",
            max_tokens=100, timeout=10,
        )

    assert (reply, reason) == ("ok", "")
    assert seen == [{"x-existing": "keep"}]


def test_goal_judge_kanban_call_binds_task_scope():
    """Kanban goal-judge path binds kanban-goal:<task_id> (#112043 follow-up)."""
    from agent import auxiliary_client as aux

    seen = []

    def call_llm(**kwargs):
        seen.append(aux._runtime_main_value("session_id"))
        return _response()

    with patch.object(aux, "call_llm", call_llm):
        raw = goals_mod._call_goal_judge_llm(
            call_llm, "sys", "user", 10, task_id="t_9")
    assert raw == "ok"
    assert seen == ["kanban-goal:t_9"]


def test_goal_judge_goal_text_stabilizes_key():
    """Plain goal loop binds a goal-text-derived stable key; same text -> same key."""
    from agent import auxiliary_client as aux

    seen = []

    def call_llm(**kwargs):
        seen.append(aux._runtime_main_value("session_id"))
        return _response()

    with patch.object(aux, "call_llm", call_llm):
        goals_mod._call_goal_judge_llm(call_llm, "sys", "user", 10, goal_text="ship the API")
    assert seen and seen[0].startswith("goal:")

    seen2 = []

    def call_llm2(**kwargs):
        seen2.append(aux._runtime_main_value("session_id"))
        return _response()

    with patch.object(aux, "call_llm", call_llm2):
        goals_mod._call_goal_judge_llm(call_llm2, "sys", "user", 10, goal_text="ship the API")
    assert seen2 == [seen[0]]
