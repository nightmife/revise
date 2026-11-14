from __future__ import annotations

import io
import json
import urllib.error

import pytest

from revise import cli, config
from revise.engines import embedded, online, prompt
from revise.engines.online import OnlineEngine
from revise.models import ReviseError

PAGES = [
    "Les piles\nUne pile est une structure de données LIFO : dernier arrivé, premier sorti.",
    "",
    "Les files\nUne file est une structure FIFO. Enfiler et défiler se font en temps constant.",
]


def reply(*cards, title="Piles et files"):
    return json.dumps({"title": title, "cards": list(cards)})


def card(q, a, page=1, kind="qa"):
    return {"kind": kind, "question": q, "answer": a, "page": page, "section": "Structures"}


@pytest.fixture
def pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt, "page_texts", lambda p: PAGES)
    return tmp_path / "[ALGO] CM1 - Piles.pdf"


# ------------------------------------------------------------- tronc commun ---

def test_generate_cards_filters_and_retries(pdf):
    replies = ["pas du json", "```json\n" + reply(
        card("Qu'est-ce qu'une pile ?", "Une structure de données LIFO : dernier arrivé, premier sorti.", 1),
        card("Qu'est-ce qu'une pile ?", "Doublon.", 1),
        card("Quelle est la capitale de l'Australie ?", "Canberra, depuis 1913 officiellement.", 1),  # inventée
        card("Que signifie FIFO pour une file ?", "La file est une structure FIFO.", 99, kind="bizarre"),
        card("", "vide", 3),
    ) + "\n```"]
    seen: list[tuple[str, str]] = []

    def chat(system, user):
        seen.append((system, user))
        return replies.pop(0)

    msgs: list[str] = []
    title, cards = prompt.generate_cards(pdf, "Algo", msgs.append, chat, "IA test")
    assert title == "Piles et files" and len(seen) == 2
    assert [c.question for c in cards] == ["Qu'est-ce qu'une pile ?", "Que signifie FIFO pour une file ?"]
    assert cards[0].page == 1 and cards[1].page is None and cards[1].kind == "qa"
    assert "=== Page 3 ===" in seen[0][1] and "Matière : Algo" in seen[0][1] and "JSON" in seen[0][0]
    assert msgs == ["IA test : pages 1-3 — morceau 1/1"]


def test_generate_cards_errors(pdf, monkeypatch):
    with pytest.raises(ReviseError, match="aucune carte"):
        prompt.generate_cards(pdf, "Algo", lambda m: None, lambda s, u: "{}", "IA test")
    monkeypatch.setattr(prompt, "page_texts", lambda p: ["", " "])
    with pytest.raises(ReviseError, match="scanné"):
        prompt.generate_cards(pdf, "Algo", lambda m: None, lambda s, u: "", "IA test")


def test_text_chunks():
    pages = ["a" * 3000, "", "b" * 3000, "c" * 3000, "d" * 20000]
    chunks = prompt.text_chunks(pages)
    assert [(f, l) for f, l, _ in chunks] == [(1, 3), (4, 4), (5, 5)]
    assert all(len(t) <= prompt.CHUNK_CHARS + 100 for _, _, t in chunks)
    assert prompt.text_chunks(["", " "]) == []


# ------------------------------------------------------------- IA en ligne ---

def http_error(code, body=None, headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(json.dumps(body or {}).encode()))


def test_online_engine(pdf):
    config.save({"online_provider": "gemini", "online_key": "cle-secrete"})
    calls, waits = [], []
    answers = [http_error(429, headers={"Retry-After": "2"}),
               {"choices": [{"message": {"content": reply(
                   card("Qu'est-ce qu'une file ?", "Une structure FIFO : enfiler et défiler en temps constant.", 3))}}]},
               {"choices": [{"message": {"content": json.dumps({"items": [{"n": 1, "wrong": [
                   "Une structure LIFO : empiler et dépiler en temps constant.",
                   "Une structure FIFO : enfiler et défiler en temps constant.",      # la bonne réponse : écartée
                   "Une structure triée : insérer et retirer en temps logarithmique."]}]})}}]}]

    def post(url, headers, payload, timeout):
        calls.append((url, headers, payload))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    engine = OnlineEngine(post, waits.append)
    assert engine.name == "en-ligne"
    _, cards = engine.generate(pdf, "Algo", lambda m: None)
    assert len(cards) == 1 and cards[0].page == 3 and waits == [2.0] and len(calls) == 3
    assert cards[0].distractors == ["Une structure LIFO : empiler et dépiler en temps constant.",
                                    "Une structure triée : insérer et retirer en temps logarithmique."]
    assert "Bonne réponse" in calls[2][2]["messages"][1]["content"]
    url, headers, payload = calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert headers["Authorization"] == "Bearer cle-secrete" and payload["model"] == "gemini-2.5-flash"
    assert payload["response_format"] == {"type": "json_object"}


def test_online_errors(pdf, monkeypatch):
    with pytest.raises(ReviseError, match="Aucune clé"):
        OnlineEngine(lambda *a: {}).generate(pdf, "Algo", lambda m: None)
    monkeypatch.setenv("REVISE_CLE_API", "x")

    def refused(*a):
        raise http_error(401, {"error": {"message": "Invalid API Key"}})

    with pytest.raises(ReviseError, match="Clé API refusée.*Invalid API Key"):
        OnlineEngine(refused).generate(pdf, "Algo", lambda m: None)

    def unknown(*a):
        raise http_error(404, [{"error": {"message": "model not found"}}])

    with pytest.raises(ReviseError, match="Modèle.*model not found"):
        OnlineEngine(unknown).generate(pdf, "Algo", lambda m: None)

    def down(*a):
        raise urllib.error.URLError("pas de réseau")

    with pytest.raises(ReviseError, match="connexion"):
        OnlineEngine(down).generate(pdf, "Algo", lambda m: None)


def test_cle_command(tmp_path, capsys):
    base = str(tmp_path / "r.db")
    assert cli.main(["--base", base, "cle", "--fournisseur", "groq", "--cle", "gsk_abc"]) == 0
    s = online.settings()
    assert (s["provider"], s["key"], s["model"]) == ("groq", "gsk_abc", "llama-3.3-70b-versatile")
    assert cli.main(["--base", base, "cle", "--modele", "autre-modele"]) == 0
    assert online.settings()["model"] == "autre-modele" and online.settings()["key"] == "gsk_abc"
    out = capsys.readouterr().out
    assert "enregistrée" in out and "gsk_abc" not in out


# ------------------------------------------------------------- IA intégrée ---

def test_pick_model_and_assets(monkeypatch):
    assert embedded.pick_model(16.5e9) == "12b" and embedded.pick_model(8e9) == "4b" and embedded.pick_model(0) == "4b"
    monkeypatch.setenv("REVISE_IA_MODELE", "4b")
    assert embedded.pick_model(64e9) == "4b"
    tag = embedded.LLAMA_TAG
    assert embedded.server_asset("vulkan", "win32") == f"llama-{tag}-bin-win-vulkan-x64.zip"
    assert embedded.server_asset("cpu", "win32") == f"llama-{tag}-bin-win-cpu-x64.zip"
    assert embedded.server_asset("vulkan", "linux") == f"llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz"
    assert embedded.server_asset("cpu", "linux") == f"llama-{tag}-bin-ubuntu-x64.tar.gz"
    assert embedded.server_asset("mac", "darwin", "arm64") == f"llama-{tag}-bin-macos-arm64.tar.gz"
    assert embedded.server_asset("mac", "darwin", "x86_64") == f"llama-{tag}-bin-macos-x64.tar.gz"
    assert [k for k, _ in embedded.server_kinds("darwin")] == ["mac", "mac"]
    assert [k for k, _ in embedded.server_kinds("linux")] == ["vulkan", "vulkan", "cpu"]
    with pytest.raises(ReviseError):
        embedded.server_asset("cpu", "sunos")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_resumes(tmp_path):
    data = bytes(range(256)) * 40
    dest = tmp_path / "ia" / "modele.gguf"
    dest.parent.mkdir()
    dest.with_name("modele.gguf.part").write_bytes(data[:1000])
    requests = []

    def opener(req, timeout):
        requests.append(req.get_header("Range"))
        return FakeResponse(data[1000:], 206)

    msgs: list[str] = []
    assert embedded.download("http://x/m", dest, msgs.append, "l'IA", len(data), opener) == dest
    assert dest.read_bytes() == data and requests == ["bytes=1000-"] and "100 %" in msgs[-1]
    assert embedded.download("http://x/m", dest, msgs.append, "l'IA", len(data), None) == dest   # déjà là : aucun appel

    def truncated(req, timeout):
        return FakeResponse(data[:10], 200)

    with pytest.raises(ReviseError, match="incomplet"):
        embedded.download("http://x/m", tmp_path / "ia" / "autre.gguf", msgs.append, "l'IA", len(data), truncated)
    assert (tmp_path / "ia" / "autre.gguf.part").stat().st_size == 10   # gardé pour la reprise

    def offline(req, timeout):
        raise urllib.error.URLError("hors ligne")

    with pytest.raises(ReviseError, match="reprendra"):
        embedded.download("http://x/m", tmp_path / "ia" / "autre.gguf", msgs.append, "l'IA", len(data), offline)


# ---------------------------------------------------------- réponses pièges ---

def test_distractors_parse_and_clean():
    from revise.engines import distractors as d

    raw = "```json\n" + json.dumps({"items": [
        {"n": 1, "wrong": ["O(n)", " o(N LOG N). ", "O(n)", "", "Toutes les réponses ci-dessus", 3, "O(n^2)", "O(1)"]},
        {"n": 7, "wrong": ["hors lot"]}, {"n": True, "wrong": ["x"]}, "n'importe quoi"]}) + "\n```"
    found = d.parse(raw, 2)
    assert list(found) == [1]
    assert d.clean("O(n log n)", found[1]) == ["O(n)", "O(n^2)", "O(1)"]
    assert d.parse("pas du json", 2) == {} and d.parse("[]", 2) == {}


def test_prepare_fills_only_missing_cards_and_survives_failures(tmp_path):
    from revise.db import Database
    from revise.engines import distractors as d
    from revise.models import CardDraft

    db = Database(tmp_path / "p.db")
    deck = db.add_deck("Algo", "CM1", None, None, "simple",
                       [CardDraft("qa", f"Question {i} ?", f"Réponse {i}", i + 1) for i in range(d.BATCH + 3)]
                       + [CardDraft("qa", "Déjà prête ?", "Oui", 99, "", ["Non"])])
    seen = []

    def chat(system, user, schema):
        seen.append(user)
        if len(seen) == 2:
            raise ReviseError("service saturé")
        return json.dumps({"items": [{"n": n, "wrong": ["a", "b", "c"]} for n in range(1, d.BATCH + 1)]})

    with pytest.raises(ReviseError):
        d.prepare(db, [deck], chat, lambda m: None)
    cards = db.cards(deck_id=deck)
    assert sum(1 for c in cards if c.distractors) == d.BATCH + 1          # le premier lot est gardé
    assert "Matière : Algo" in seen[0] and "Déjà prête" not in "".join(seen) and schema_ok(d.SCHEMA)
    assert d.prepare(db, [deck], lambda s, u, sch: json.dumps({"items": [
        {"n": n, "wrong": ["a", "b", "c"]} for n in range(1, 4)]}), lambda m: None) == 3
    assert all(c.distractors for c in db.cards(deck_id=deck))
    assert d.prepare(db, [deck], chat, lambda m: None) == 0 and len(seen) == 2   # plus rien à faire : aucun appel
    db.close()


def schema_ok(schema) -> bool:
    return schema["required"] == ["items"] and schema["additionalProperties"] is False


def test_default_engine_follows_settings(monkeypatch):
    from revise.engines import distractors as d

    assert d.default_engine_name() == "ia"
    config.save({"online_key": "abc"})
    assert d.default_engine_name() == "en-ligne"
    config.save({"engine": "ia"})
    assert d.default_engine_name() == "ia"                 # choix explicite de l'IA locale : on ne l'outrepasse pas
    config.save({"engine": "en-ligne"})
    assert d.default_engine_name() == "en-ligne"


def test_mac_folders(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.delenv("REVISE_CONFIG")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    support = tmp_path / "Library" / "Application Support" / "revise"
    assert config.data_dir() == support and config.config_path() == support / "config.json"
