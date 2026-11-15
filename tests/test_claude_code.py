"""Moteur « abonnement » (claude -p) testé avec un faux exécutable."""

import json
from types import SimpleNamespace

import pytest

from revise import config
from revise.engines import claude_code, distractors, prompt
from revise.engines.claude_code import ClaudeCodeEngine
from revise.models import ReviseError


@pytest.fixture(autouse=True)
def fake_binary(monkeypatch):
    monkeypatch.setattr(claude_code, "claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ne-doit-pas-etre-transmise")
    monkeypatch.setattr(prompt, "page_texts", lambda p: ["Les piles\nUne pile est une structure de données LIFO."])


def ok(data, structured=True):
    outer = {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(data)}
    if structured:
        outer["structured_output"] = data
    return SimpleNamespace(returncode=0, stdout=json.dumps(outer), stderr="")


def test_generate_cards_and_traps(tmp_path):
    calls = []

    def runner(cmd, cwd, env, input, **kw):
        calls.append((cmd, env, input))
        if len(calls) == 1:
            return ok({"title": "Piles", "cards": [{"kind": "qa", "question": "Qu'est-ce qu'une pile ?",
                                                     "answer": "Une structure de données LIFO.", "page": 1,
                                                     "section": "Piles"}]})
        return ok({"items": [{"n": 1, "wrong": ["Une structure FIFO.", "Un arbre.", "Un tas."]}]}, structured=False)

    engine = ClaudeCodeEngine(runner)
    assert engine.name == "abonnement"
    _, cards = engine.generate(tmp_path / "CM1 - Piles.pdf", "Algo", lambda m: None)
    assert len(cards) == 1 and cards[0].distractors == ["Une structure FIFO.", "Un arbre.", "Un tas."]
    cmd, env, text = calls[0]
    assert cmd[:2] == ["/usr/bin/claude", "-p"] and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "=== Page 1 ===" in text      # aucun outil, cours passé en entrée
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"] == ["title", "cards"]
    assert json.loads(calls[1][0][calls[1][0].index("--json-schema") + 1]) == distractors.SCHEMA
    assert "ANTHROPIC_API_KEY" not in env                                        # jamais la clé payante


def test_errors(monkeypatch):
    limit = SimpleNamespace(returncode=1, stderr="", stdout=json.dumps(
        {"type": "result", "subtype": "success", "is_error": True, "result": "Claude usage limit reached"}))
    with pytest.raises(ReviseError, match="limite"):
        ClaudeCodeEngine(lambda *a, **k: limit).chat("s", "u")
    garbage = SimpleNamespace(returncode=1, stdout="", stderr="command failed")
    with pytest.raises(ReviseError, match="command failed"):
        ClaudeCodeEngine(lambda *a, **k: garbage).chat("s", "u")
    monkeypatch.setattr(claude_code, "claude_binary", lambda: None)
    with pytest.raises(ReviseError, match="introuvable"):
        ClaudeCodeEngine().check()


def test_chosen_for_traps_when_selected():
    config.save({"engine": "abonnement", "online_key": "abc"})
    assert distractors.default_engine_name() == "abonnement"
    assert isinstance(distractors.default_engine(), ClaudeCodeEngine)


def test_chat_pdf_sends_the_document_without_any_tool():
    import base64
    calls = []

    def runner(cmd, cwd, env, input, **kw):
        calls.append((cmd, input))
        lines = [{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}},
                 {"type": "result", "subtype": "success", "is_error": False, "result": "x",
                  "structured_output": {"title": "T", "cards": []}}]
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(x) for x in lines), stderr="")

    out = ClaudeCodeEngine(runner).chat_pdf("consignes", "message", b"%PDF-1.4 faux")
    assert json.loads(out) == {"title": "T", "cards": []}
    [(cmd, sent)] = calls
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--input-format") + 1] == "stream-json"
    message = json.loads(sent)
    document, text = message["message"]["content"]
    assert document["type"] == "document" and document["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document["source"]["data"]) == b"%PDF-1.4 faux"
    assert text == {"type": "text", "text": "message"}


def test_stream_output_without_result_is_an_error():
    def runner(cmd, cwd, env, input, **kw):
        return SimpleNamespace(returncode=1, stdout='{"type": "system"}\npas du json', stderr="")
    with pytest.raises(ReviseError):
        ClaudeCodeEngine(runner).chat_pdf("s", "u", b"x")
