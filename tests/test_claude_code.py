"""Moteur abonnement (claude -p) testé avec un faux exécutable."""

import json
from types import SimpleNamespace

import pytest

from revise.engines import claude_code
from revise.engines.claude_code import ClaudeCodeEngine
from revise.models import ReviseError


@pytest.fixture(autouse=True)
def fake_binary(monkeypatch):
    monkeypatch.setattr(claude_code, "claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-ne-doit-pas-etre-transmise")


def ok(cards, structured=True):
    data = {"title": "Piles", "cards": cards}
    outer = {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(data)}
    if structured:
        outer["structured_output"] = data
    return SimpleNamespace(returncode=0, stdout=json.dumps(outer), stderr="")


def test_command_env_and_chunks(pdf_factory):
    calls = []

    def runner(cmd, cwd, env, **kw):
        calls.append((cmd, cwd, env))
        assert (__import__("pathlib").Path(cwd) / "cours.pdf").exists()
        return ok([{"kind": "qa", "question": f"Q{len(calls)}", "answer": "R", "page": 1, "section": ""}],
                  structured=len(calls) == 1)

    title, cards = ClaudeCodeEngine(runner, pages_per_chunk=20).generate(pdf_factory(30), "Algo", lambda m: None)
    assert len(calls) == 2
    cmd, _, env = calls[0]
    assert cmd[:2] == ["/usr/bin/claude", "-p"]
    assert "--json-schema" in cmd and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert "ANTHROPIC_API_KEY" not in env  # jamais la clé payante
    assert "pages 21 à 30" in calls[1][0][2]
    assert title == "Piles"
    assert [c.page for c in cards] == [1, 21]


def test_errors(pdf_factory):
    pdf = pdf_factory(2)
    limit = SimpleNamespace(returncode=1, stderr="", stdout=json.dumps(
        {"type": "result", "subtype": "success", "is_error": True, "result": "Claude usage limit reached"}))
    with pytest.raises(ReviseError, match="limite"):
        ClaudeCodeEngine(lambda *a, **k: limit).generate(pdf, "A", lambda m: None)
    garbage = SimpleNamespace(returncode=1, stdout="", stderr="command failed")
    with pytest.raises(ReviseError, match="command failed"):
        ClaudeCodeEngine(lambda *a, **k: garbage).generate(pdf, "A", lambda m: None)


def test_missing_binary(pdf_factory, monkeypatch):
    monkeypatch.setattr(claude_code, "claude_binary", lambda: None)
    with pytest.raises(ReviseError, match="introuvable"):
        ClaudeCodeEngine().generate(pdf_factory(1), "A", lambda m: None)
