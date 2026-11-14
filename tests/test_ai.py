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
                   card("Qu'est-ce qu'une file ?", "Une structure FIFO : enfiler et défiler en temps constant.", 3))}}]}]

    def post(url, headers, payload, timeout):
        calls.append((url, headers, payload))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    engine = OnlineEngine(post, waits.append)
    assert engine.name == "en-ligne"
    _, cards = engine.generate(pdf, "Algo", lambda m: None)
    assert len(cards) == 1 and cards[0].page == 3 and waits == [2.0] and len(calls) == 2
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
    with pytest.raises(ReviseError):
        embedded.server_asset("cpu", "darwin")


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
