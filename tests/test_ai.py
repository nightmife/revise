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
    config.save({"online_keyless": False})
    with pytest.raises(ReviseError, match="Aucune clé"):
        OnlineEngine(lambda *a: {}).generate(pdf, "Algo", lambda m: None)
    config.save({"online_provider": "groq"})
    monkeypatch.setenv("REVISE_CLE_API", "x")

    def refused(*a):
        raise http_error(401, {"error": {"message": "Invalid API Key"}})

    with pytest.raises(ReviseError, match="Groq : clé API refusée.*Invalid API Key"):
        OnlineEngine(refused).generate(pdf, "Algo", lambda m: None)

    def unknown(*a):
        raise http_error(404, [{"error": {"message": "model not found"}}])

    with pytest.raises(ReviseError, match="modèle.*model not found"):
        OnlineEngine(unknown, get=lambda *a: {"data": []}).generate(pdf, "Algo", lambda m: None)

    def down(*a):
        raise urllib.error.URLError("pas de réseau")

    with pytest.raises(ReviseError, match="connexion"):
        OnlineEngine(down).generate(pdf, "Algo", lambda m: None)


def test_online_replaces_a_retired_model_and_explains_missing_quota(pdf):
    config.save({"online_provider": "groq", "online_key": "k"})
    calls = []

    def post(url, headers, payload, timeout):
        calls.append(payload["model"])
        if payload["model"] == "llama-3.3-70b-versatile":
            raise http_error(400, {"error": {"message": "The model has been decommissioned"}})
        return {"choices": [{"message": {"content": reply(
            card("Qu'est-ce qu'une file ?", "Une structure FIFO : enfiler et défiler en temps constant.", 3))}}]}

    def get(url, headers, timeout):
        assert url == "https://api.groq.com/openai/v1/models" and headers["Authorization"] == "Bearer k"
        return {"data": [{"id": i} for i in ("whisper-large-v3", "openai/gpt-oss-20b", "openai/gpt-oss-120b",
                                             "meta-llama/llama-guard-4-12b")]}

    msgs = []
    _, cards = OnlineEngine(post, lambda s: None, get=get).generate(pdf, "Algo", msgs.append)
    assert len(cards) == 1 and calls[:2] == ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
    assert online.settings()["model"] == "openai/gpt-oss-120b" and any("n'existe plus" in m for m in msgs)
    assert online.pick_model(["models/gemini-2.5-flash-lite", "models/gemini-2.5-flash", "models/gemini-3-flash",
                              "models/gemini-embedding-001"], "gemini") == "gemini-3-flash"
    assert online.pick_model(["whisper-large-v3"], "groq") == ""

    def no_quota(*a):
        raise http_error(429, {"error": {"message": "Quota exceeded for metric free_tier_requests, limit: 0"}})

    waits = []
    with pytest.raises(ReviseError, match="aucune utilisation gratuite.*limit: 0"):
        OnlineEngine(no_quota, waits.append).generate(pdf, "Algo", lambda m: None)
    assert waits == []                                   # pas d'attente inutile


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


def test_https_uses_bundled_certificates():
    from revise import net

    assert net.ssl_context().cert_store_stats()["x509_ca"] > 50
    assert net.reason(urllib.error.URLError("certificat refusé")) == "certificat refusé"


# ---------------------------------------------------------- réponses pièges ---

def test_distractors_parse_and_clean():
    from revise.engines import distractors as d

    raw = "```json\n" + json.dumps({"items": [
        {"n": 1, "wrong": ["O(n)", " o(N LOG N). ", "O(n)", "", "Toutes les réponses ci-dessus", 3, "O(n^2)", "O(1)"]},
        {"n": 7, "wrong": ["hors lot"]}, {"n": True, "wrong": ["x"]}, "n'importe quoi"]}) + "\n```"
    found = d.parse(raw, 2)
    assert list(found) == [1]
    assert d.clean("O(n log n)", found[1][1]) == ["O(n)", "O(n^2)", "O(1)"]
    assert d.clean("O(n log n)", ["O(n)", "Θ(n log n)"], right="Θ(n log n)") == ["O(n)"]
    assert d.parse("pas du json", 2) == {} and d.parse("[]", 2) == {}
    # bonne réponse réécrite : gardée si elle est raisonnable, sinon celle du cours
    assert d.clean_right("Une pile, car LIFO : le dernier entré sort en premier.", " Une pile ") == "Une pile"
    assert d.clean_right("Une pile", "") == "Une pile" and d.clean_right("Une pile", None) == "Une pile"
    assert d.clean_right("Une pile", "x" * 200) == "Une pile"


def test_traps_balanced_retry():
    """Bonne réponse bien plus longue que les pièges : les quatre propositions sont redemandées une fois."""
    from revise.engines import distractors as d

    long_answer = "Une pile, parce que le dernier élément ajouté est toujours le premier à être retiré (LIFO)."
    assert d.imbalance(long_answer, ["Une file.", "Un arbre.", "Un tas."]) > 1
    assert d.imbalance("Une pile.", ["Une file.", "Un arbre.", "Un tas."]) < 1
    calls = []

    def chat(system, user, schema):
        calls.append((system, user))
        if len(calls) == 1:   # 1er essai : la bonne réponse dépasse ; la 2e question est équilibrée
            return json.dumps({"items": [{"n": 1, "right": long_answer, "wrong": ["Une file.", "Un arbre.", "Un tas."]},
                                         {"n": 2, "right": "O(n)", "wrong": ["O(1)", "O(n²)", "O(log n)"]}]})
        return json.dumps({"items": [{"n": 1, "right": "Une pile : dernier entré, premier sorti.",
                                      "wrong": ["Une file : premier entré, premier sorti.",
                                                "Un arbre : parcouru en largeur d'abord.",
                                                "Un tas : le plus petit sort en premier."]}]})

    got = d.ask([("qa", "Quelle structure ?", long_answer), ("qa", "Coût ?", "O(n)")], "Algo", chat)
    assert len(calls) == 2 and "ATTENTION" in calls[1][0] and "Coût" not in calls[1][1]
    assert "Longueur visée" in calls[1][1]
    assert got[0][0] == "Une pile : dernier entré, premier sorti." and len(got[0][1]) == 3
    assert got[1] == ("O(n)", ["O(1)", "O(n²)", "O(log n)"])
    # deuxième essai pire que le premier (ou en panne) : le premier est gardé
    calls.clear()
    got = d.ask([("qa", "Quelle structure ?", long_answer)], "Algo",
                lambda s, u, sch: (calls.append(1), json.dumps({"items": [{"n": 1, "right": long_answer, "wrong": [
                    "Une file.", "Un arbre.", "Un tas."]}]}))[1])
    assert len(calls) == 2 and got[0][0] == long_answer and len(got[0][1]) == 3


def test_prepare_fills_only_missing_cards_and_survives_failures(tmp_path):
    from revise.db import Database
    from revise.engines import distractors as d
    from revise.models import CardDraft

    db = Database(tmp_path / "p.db")
    deck = db.add_deck("Algo", "CM1", None, None, "simple",
                       [CardDraft("qa", f"Question {i} ?", f"Réponse {i}", i + 1) for i in range(d.BATCH + 3)]
                       + [CardDraft("qa", "Déjà prête ?", "Oui", 99, "", ["Non"], "Oui")])
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
    assert d.SCHEMA["properties"]["items"]["items"]["required"] == ["n", "right", "wrong"]
    assert d.prepare(db, [deck], lambda s, u, sch: json.dumps({"items": [
        {"n": n, "wrong": ["a", "b", "c"]} for n in range(1, 4)]}), lambda m: None) == 3
    assert all(c.distractors and c.quiz_answer for c in db.cards(deck_id=deck))
    assert d.prepare(db, [deck], chat, lambda m: None) == 0 and len(seen) == 2   # plus rien à faire : aucun appel
    # carte modifiée : ses propositions de QCM sont à refaire
    first = db.cards(deck_id=deck)[0]
    db.update_card_content(first.id, "qa", first.question, "Autre réponse", first.page)
    assert not db.card(first.id).distractors and not db.card(first.id).quiz_answer
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


# ------------------------------------------------------- pages scannées, schémas

def scanned_pdf(path, pages: int, big_image_on=(), logo: bool = False):
    """PDF sans texte ; une grande image sur les pages `big_image_on`, un « logo » partout si demandé."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject
    w = PdfWriter()

    def image(width, height):
        s = StreamObject()
        s[NameObject("/Type")] = NameObject("/XObject")
        s[NameObject("/Subtype")] = NameObject("/Image")
        s[NameObject("/Width")], s[NameObject("/Height")] = NumberObject(width), NumberObject(height)
        s[NameObject("/ColorSpace")], s[NameObject("/BitsPerComponent")] = NameObject("/DeviceGray"), NumberObject(8)
        s._data = b"\x00"
        return w._add_object(s)
    shared = image(400, 300) if logo else None
    for n in range(1, pages + 1):
        page = w.add_blank_page(width=595, height=842)
        xobjects = DictionaryObject()
        if shared is not None:
            xobjects[NameObject("/Logo")] = shared
        if n in big_image_on:
            xobjects[NameObject("/Im1")] = image(1200, 900)
        xobjects[NameObject("/Puce")] = image(16, 16)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): xobjects})
    w.write(str(path))
    return path


def test_visual_pages_detects_scans_and_diagrams_but_not_logos(tmp_path):
    from revise.pdf import visual_pages
    text = "Une pile est une structure de données LIFO, le dernier arrivé est le premier sorti. " * 2
    f = scanned_pdf(tmp_path / "a.pdf", 6, big_image_on=(2, 5), logo=True)
    #  1 texte + logo · 2 schéma · 3 texte · 4 presque vide + logo · 5 scan sans texte · 6 texte
    assert visual_pages(f, [text, text, text, "Merci", "", text]) == {2, 4, 5}
    assert visual_pages(scanned_pdf(tmp_path / "b.pdf", 3), ["", "x", text]) == set()      # que des puces : rien à voir
    assert visual_pages(tmp_path / "cours.pptx", ["", ""]) == set()


def test_chunks_keep_visual_pages_apart():
    pages = ["texte un", "", "schéma", "", "texte cinq", "texte six", ""]
    assert prompt.text_chunks(pages) == [(1, 7, "=== Page 1 ===\ntexte un\n\n=== Page 3 ===\nschéma\n\n"
                                                "=== Page 5 ===\ntexte cinq\n\n=== Page 6 ===\ntexte six")]
    chunks = prompt.text_chunks(pages, {3, 4})
    assert [(a, b) for a, b, _ in chunks] == [(1, 2), (3, 4), (5, 7)]
    assert prompt.NO_TEXT in chunks[1][2] and "=== Page 4 ===" in chunks[1][2]
    assert [(a, b) for a, b, _ in prompt.text_chunks(["", "", ""], {2, 3})] == [(2, 3)]      # tout scanné
    many = prompt.text_chunks(["x"] * 15, set(range(1, 16)))
    assert [(a, b) for a, b, _ in many] == [(1, 6), (7, 12), (13, 15)]


def test_scanned_pdf_goes_through_chat_pdf(tmp_path, monkeypatch):
    from pypdf import PdfReader
    f = scanned_pdf(tmp_path / "scan.pdf", 3, big_image_on=(1, 2, 3))
    monkeypatch.setattr(prompt, "page_texts", lambda p: ["", "", "Conclusion du cours sur les piles et les files, à retenir."])
    sent = []

    def chat_pdf(system, user, document):
        sent.append((system, user, len(PdfReader(__import__("io").BytesIO(document)).pages)))
        return json.dumps({"title": "Piles", "cards": [
            {"kind": "qa", "question": "Que montre le schéma de la pile ?", "answer": "Le sommet est en haut.",
             "page": 2, "section": "Piles"}]})

    def chat(system, user):
        raise AssertionError("une page à regarder ne doit pas partir en texte seul")
    title, cards = prompt.generate_cards(f, "Algo", lambda m: None, chat, "IA", chat_pdf)
    assert title == "Piles" and [(c.page, c.question) for c in cards] == [(2, "Que montre le schéma de la pile ?")]
    [(system, user, n_pages)] = sent
    assert n_pages == 3 and prompt.VISUAL_RULES in system and prompt.NO_TEXT in user
    assert "sa première page est la page 1 du cours" in user

    # Un moteur qui ne sait pas regarder : message clair pour un PDF entièrement scanné
    monkeypatch.setattr(prompt, "page_texts", lambda p: ["", "", ""])
    with pytest.raises(ReviseError, match="abonnement Claude"):
        prompt.generate_cards(f, "Algo", lambda m: None, chat, "IA")


def test_oversized_visual_chunk_is_sent_page_by_page(tmp_path, monkeypatch):
    f = scanned_pdf(tmp_path / "gros.pdf", 2, big_image_on=(1, 2))
    monkeypatch.setattr(prompt, "page_texts", lambda p: ["", "Texte de la page deux sur les arbres binaires."])
    monkeypatch.setattr(prompt, "MAX_PDF_BYTES", 10)                      # tout est « trop lourd »
    asked = []

    def chat(system, user):
        asked.append(user)
        return json.dumps({"title": "T", "cards": [{"kind": "qa", "question": "Qu'est-ce qu'un arbre binaire ?",
                                                     "answer": "Arbres binaires : deux fils au plus.", "page": 2,
                                                     "section": ""}]})
    _, cards = prompt.generate_cards(f, "Algo", lambda m: None, chat, "IA", lambda s, u, d: pytest.fail("trop lourd"))
    assert len(asked) == 1 and "=== Page 2 ===" in asked[0] and len(cards) == 1    # la page 1, illisible, est laissée


# ------------------------------------------- plusieurs services, service sans clé

def ok_reply(text):
    return {"choices": [{"message": {"content": text}}]}


def test_online_chain_order_and_legacy_settings():
    assert [c["provider"] for c in online.chain()] == [online.KEYLESS]    # rien de réglé : marche sans clé
    assert online.describe() == "sans clé : marche, mais lent" and not online.has_key()
    config.save({"online_provider": "gemini", "online_key": "ancienne"})  # réglages d'avant la 0.8
    assert online.settings()["key"] == "ancienne" and online.has_key()
    config.save({"online_keys": {"groq": "g", "mistral": "m", "inconnu": "x", "cerebras": " "}})
    assert [c["provider"] for c in online.chain()] == ["gemini", "groq", "mistral", online.KEYLESS]
    assert online.settings("mistral") == {"provider": "mistral", "url": "https://api.mistral.ai/v1",
                                          "model": "mistral-small-latest", "key": "m"}
    config.save({"online_keyless": False})
    assert [c["provider"] for c in online.chain()] == ["gemini", "groq", "mistral"]
    assert online.describe() == "prête : Google Gemini, Groq, Mistral AI"
    config.save({"online_provider": online.KEYLESS})
    assert online.chain()[0]["provider"] == online.KEYLESS                # choisi exprès : essayé en premier
    assert online.pick_model(["openai/gpt-5", "google/gemma-4-31b-it:free"], "openrouter") == \
        "google/gemma-4-31b-it:free"                                       # jamais un modèle payant


def test_online_switches_service_when_quota_is_exhausted():
    config.save({"online_provider": "groq", "online_keys": {"groq": "g", "cerebras": "c"}})
    calls, waits, msgs = [], [], []

    def post(url, headers, payload, timeout):
        calls.append((url, headers.get("Authorization")))
        if "groq" in url:
            raise http_error(429, {"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 100000"}})
        return ok_reply('{"ok": 1}')

    engine = OnlineEngine(post, waits.append)
    engine.progress = msgs.append
    assert engine.chat("s", "u") == '{"ok": 1}' and engine.chat("s", "u") == '{"ok": 1}'
    assert [u.split("/")[2] for u, _ in calls] == ["api.groq.com", "api.cerebras.ai", "api.cerebras.ai"]
    assert calls[1][1] == "Bearer c" and waits == []                       # quota du jour : pas d'attente
    assert any("on passe à Cerebras" in m for m in msgs)

    def all_down(url, headers, payload, timeout):
        raise http_error(401, {"error": {"message": "bad key"}})

    with pytest.raises(ReviseError, match=r"(?s)Aucun service.*Groq : clé API refusée.*Cerebras : clé API refusée"):
        OnlineEngine(all_down, waits.append, confs=[online.settings("groq"), online.settings("cerebras")]).chat("s", "u")


def test_keyless_service_waits_its_turn():
    calls, waits = [], []
    answers = [http_error(402, {"error": {"code": "FREE_LIMIT", "message": "Free limit reached: 1 reply every 45 "
                                          "seconds per IP. Retry after 32s, or get unlimited replies"}}),
               ok_reply('{"ok": 1}')]

    def post(url, headers, payload, timeout):
        calls.append((url, headers, payload))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    engine = OnlineEngine(post, waits.append)
    engine.check()
    assert engine.chat("s", "u") == '{"ok": 1}' and waits == [33.0]
    url, headers, payload = calls[0]
    assert url == "https://text.pollinations.ai/openai/chat/completions" and "Authorization" not in headers
    assert payload["model"] == "openai" and payload["reasoning_effort"] == "low"
    assert engine.trap_batch == online.KEYLESS_BATCH < OnlineEngine(conf=online.settings("groq")).trap_batch


def test_online_lowers_reasoning_when_the_answer_is_cut():
    seen = []

    def post(url, headers, payload, timeout):
        seen.append(payload.get("reasoning_effort"))
        if not payload.get("reasoning_effort"):
            raise http_error(400, {"error": {"message": "The model exhausted its output token limit before "
                                                        "producing an answer. Reduce reasoning effort."}})
        return ok_reply("{}")

    assert OnlineEngine(post, lambda s: None, conf=online.settings("groq") | {"key": "k"}).chat("s", "u") == "{}"
    assert seen == [None, "low"]


def test_online_drops_json_mode_when_the_model_refuses_it():
    seen = []

    def post(url, headers, payload, timeout):
        seen.append("response_format" in payload)
        if payload.get("response_format"):
            raise http_error(400, {"error": {"message": "response_format json_object is not supported"}})
        return ok_reply("{}")

    assert OnlineEngine(post, lambda s: None, conf=online.settings(online.KEYLESS)).chat("s", "u") == "{}"
    assert seen == [True, False]


def test_online_choices_match_cli():
    import argparse
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices["cle"]
    assert next(a for a in sub._actions if a.dest == "fournisseur").choices == list(online.PROVIDERS)


def test_cle_command_keeps_one_key_per_service(tmp_path):
    base = str(tmp_path / "r.db")
    assert cli.main(["--base", base, "cle", "--fournisseur", "groq", "--cle", "g"]) == 0
    assert cli.main(["--base", base, "cle", "--fournisseur", "cerebras", "--cle", "c", "--sans-cle", "non"]) == 0
    assert [c["provider"] for c in online.chain()] == ["cerebras", "groq"]
    assert online.settings("groq")["key"] == "g"
