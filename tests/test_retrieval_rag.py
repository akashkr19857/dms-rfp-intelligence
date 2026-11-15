from __future__ import annotations

import pytest

from app.llm import FakeLLM, set_llm
from app.rag import NOT_FOUND, answer, extract_citations
from app.retrieval.bm25 import tokenize
from app.retrieval.hybrid import retrieve, rrf


@pytest.fixture()
def fake_llm():
    llm = FakeLLM(lambda m: "The GOVERN function is cross-cutting [1]. Inventory AI systems [2]. Bogus [9].")
    set_llm(llm)
    yield llm
    set_llm(None)


def test_rrf_rewards_agreement():
    scores = rrf([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert max(scores, key=scores.get) in ("a", "b")
    assert scores["a"] == scores["b"] > scores["c"] > 0 and scores["d"] == scores["c"]


def test_tokenize_drops_stopwords():
    assert tokenize("What is the GV.OC identifier of the CSF?") == ["gv.oc", "identifier", "csf"]


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_retrieval_finds_relevant_chunk(seeded, mode):
    r = retrieve("cross-cutting GOVERN function culture", ["tenders"], mode=mode, use_reranker=False)
    assert r.hits and "cross-cutting" in r.hits[0].text


def test_reranker_scores_and_sorts(seeded):
    r = retrieve("multi-factor authentication passwords", ["knowledge-base"], use_reranker=True)
    scores = [h.rerank_score for h in r.hits]
    assert scores == sorted(scores, reverse=True)
    assert "multi-factor" in r.hits[0].text


def test_workspace_isolation(seeded):
    """RBAC: a cybersecurity-only scope can never retrieve AI-governance chunks, whatever the query."""
    r = retrieve("GOVERN function cross-cutting inventory AI systems", ["knowledge-base"], use_reranker=False, top_k=20)
    assert all(h.workspace_id == "knowledge-base" for h in r.hits)
    assert retrieve("anything", [], use_reranker=False).hits == []


def test_doc_filter(seeded):
    r = retrieve("function", ["tenders", "knowledge-base"], doc_ids=[seeded["sec"]], use_reranker=False, top_k=20)
    assert r.hits and all(h.doc_id == seeded["sec"] for h in r.hits)


def test_answer_has_page_citations(seeded, fake_llm):
    a = answer("Which function is cross-cutting?", ["tenders"])
    assert not a.not_found
    assert [c["n"] for c in a.citations] == [1, 2]  # [9] is out of range and dropped
    assert all(c["page"] >= 1 and c["doc_title"] for c in a.citations)
    sys_prompt = fake_llm.calls[-1][0]["content"]
    assert "ONLY the numbered sources" in sys_prompt


def test_not_found_without_calling_llm_when_nothing_relevant(seeded, fake_llm):
    a = answer("zebra quantum pancake", ["tenders"])
    assert a.not_found and a.answer == NOT_FOUND and a.gate in ("no_hits", "low_score")
    assert fake_llm.calls == []


def test_llm_not_found_reply_is_normalised(seeded):
    set_llm(FakeLLM(lambda m: "I could not find this in the documents you have access to."))
    try:
        a = answer("Which function is cross-cutting?", ["tenders"])
    finally:
        set_llm(None)
    assert a.not_found and a.gate == "llm" and a.citations == []


def test_extract_citations_dedupes():
    class H:  # minimal hit stand-in
        def __init__(self, i):
            self.chunk_id, self.doc_id, self.doc_title, self.page, self.section = f"c{i}", 1, "Doc", i, ""

    cites = extract_citations("a [2] b [2][1] c [7]", [H(1), H(2)])
    assert [c["n"] for c in cites] == [2, 1]


ONNX_PATH = __import__("pathlib").Path(__file__).resolve().parents[1] / "edge" / "reranker.onnx"


@pytest.mark.skipif(not ONNX_PATH.exists(), reason="run edge/export_reranker_onnx.py to create the ONNX reranker")
def test_onnx_reranker_ranks_relevant_passage_first():
    from app.retrieval.reranker import OnnxReranker

    r = OnnxReranker("BAAI/bge-reranker-base", str(ONNX_PATH))
    scores = r.score("verify backups before restoring", ["The integrity of backups is verified before restoration.", "Tiers describe rigor."])
    assert scores[0] > 0.5 > scores[1]


@pytest.mark.parametrize("text,expected", [
    ("The four functions of the AI RMF Core are not explicitly listed in the provided sources. However, ... [1]", True),
    ("The provided sources do not mention the EU AI Act fines.", True),
    ("I could not find this in the documents you have access to.", True),
    ("The four functions are GOVERN, MAP, MEASURE and MANAGE [1].", False),
    ("GOVERN is cross-cutting [1]. The sources do not list a fine for this.", False),  # hedge only later → still an answer
])
def test_not_found_detection(text, expected):
    from app.rag import is_not_found

    assert is_not_found(text) is expected
