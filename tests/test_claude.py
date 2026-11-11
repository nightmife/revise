"""Moteur Claude testé avec un client simulé (aucun appel réseau)."""

import base64
import json
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
import io

from revise.engines.claude import CARD_SCHEMA, MODEL, ClaudeEngine
from revise.models import ReviseError


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Imite client.beta.messages.stream / client.messages.count_tokens."""

    def __init__(self, responder):
        self.calls = []
        self.responder = responder
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.messages = SimpleNamespace(count_tokens=self._count)

    def _stream(self, **kw):
        self.calls.append(kw)
        return FakeStream(self.responder(kw, len(self.calls)))

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=1000)


def message(cards, stop="end_turn", title="Piles"):
    text = json.dumps({"title": title, "cards": cards})
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""),
                                                      SimpleNamespace(type="text", text=text)])


def pages_in(kw) -> int:
    doc = kw["messages"][0]["content"][0]
    return len(PdfReader(io.BytesIO(base64.b64decode(doc["source"]["data"]))).pages)


def test_request_shape_and_parsing(pdf_factory):
    pdf = pdf_factory(3)
    client = FakeClient(lambda kw, n: message([
        {"kind": "qa", "question": "Qu'est-ce qu'une pile ?", "answer": "LIFO", "page": 2, "section": "Piles"},
        {"kind": "bizarre", "question": "Q", "answer": "R", "page": 99, "section": ""},
        {"kind": "qa", "question": "  ", "answer": "vide", "page": 1, "section": ""},
    ]))
    title, cards = ClaudeEngine(client).generate(pdf, "Algo", lambda m: None)
    kw = client.calls[0]
    assert kw["model"] == MODEL
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": CARD_SCHEMA}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
    assert "\n" not in content[0]["source"]["data"]
    assert pages_in(kw) == 3
    assert title == "Piles"
    assert [(c.kind, c.page) for c in cards] == [("qa", 2), ("qa", None)]  # type corrigé, page hors PDF ignorée


def test_large_pdf_is_chunked_with_page_offsets(pdf_factory):
    pdf = pdf_factory(25)

    def responder(kw, n):
        # Claude répond avec des numéros relatifs au morceau (page 1 du document joint)
        return message([{"kind": "qa", "question": f"Q{n}", "answer": "R", "page": 1, "section": ""}])

    client = FakeClient(responder)
    _, cards = ClaudeEngine(client, pages_per_chunk=10).generate(pdf, "Algo", lambda m: None)
    assert [pages_in(kw) for kw in client.calls] == [10, 10, 5]
    assert "pages 11 à 20" in client.calls[1]["messages"][0]["content"][1]["text"]
    assert [c.page for c in cards] == [1, 11, 21]


def test_max_tokens_splits_chunk(pdf_factory):
    pdf = pdf_factory(8)

    def responder(kw, n):
        if pages_in(kw) > 4:
            return message([], stop="max_tokens")
        return message([{"kind": "qa", "question": f"Q{n}", "answer": "R", "page": 1, "section": ""}])

    client = FakeClient(responder)
    _, cards = ClaudeEngine(client).generate(pdf, "Algo", lambda m: None)
    assert [pages_in(kw) for kw in client.calls] == [8, 4, 4]
    assert len(cards) == 2


def test_refusal_and_duplicates(pdf_factory):
    pdf = pdf_factory(2)
    with pytest.raises(ReviseError):
        ClaudeEngine(FakeClient(lambda kw, n: message([], stop="refusal"))).generate(pdf, "A", lambda m: None)
    dup = [{"kind": "qa", "question": "Même  question", "answer": "R", "page": 1, "section": ""},
           {"kind": "qa", "question": "même question", "answer": "R2", "page": 2, "section": ""}]
    _, cards = ClaudeEngine(FakeClient(lambda kw, n: message(dup))).generate(pdf, "A", lambda m: None)
    assert len(cards) == 1


def test_estimate(pdf_factory):
    est = ClaudeEngine(FakeClient(lambda kw, n: None), pages_per_chunk=10).estimate(pdf_factory(12), "A")
    assert (est.pages, est.chunks, est.input_tokens) == (12, 2, 2000)
    assert est.dollars > 0
