from __future__ import annotations

import json
import re

import pytest

from app.agent import compare_documents, list_documents, run_agent
from app.llm import FakeLLM, set_llm
from app.rag import NOT_FOUND

BOTH = ["tenders", "knowledge-base"]


def scripted(plan: dict):
    def respond(messages: list[dict]) -> str:
        system, user = messages[0]["content"], messages[-1]["content"]
        if system.startswith("Rewrite the user question"):
            return json.dumps({"query": "governance and authentication controls"})
        if system.startswith("You plan how to answer"):
            ids = [int(x) for x in re.findall(r"id=(\d+)", user)]
            p = dict(plan)
            if p.get("type") == "compare":
                p["doc_a"], p["doc_b"] = ids[0], ids[1]
            return json.dumps(p)
        if system.startswith("Answer the sub-question"):
            return "The GOVERN function is cross-cutting."
        return "Doc A covers governance [1] while Doc B covers authentication [2]."
    return respond


@pytest.fixture()
def use_llm():
    def _set(plan: dict) -> FakeLLM:
        llm = FakeLLM(scripted(plan))
        set_llm(llm)
        return llm
    yield _set
    set_llm(None)


def test_list_documents_respects_workspaces(seeded):
    assert {d["title"] for d in list_documents(["knowledge-base"])} == {"Security Test Doc"}
    assert len(list_documents(BOTH)) == 2


def test_compare_tool_blocks_inaccessible_docs(seeded):
    out = compare_documents(seeded["ai"], seeded["sec"], "authentication", ["knowledge-base"])
    assert out[seeded["ai"]] == []  # no access to the AI doc from a cybersecurity scope
    assert out[seeded["sec"]] and all(h.doc_id == seeded["sec"] for h in out[seeded["sec"]])


def test_agent_compare_path(seeded, use_llm):
    use_llm({"type": "compare", "aspect": "controls"})
    ans = run_agent("Compare the two documents", BOTH)
    nodes = [s["node"] for s in ans.steps]
    assert nodes == ["rewrite", "plan", "compare_documents", "synthesize"]
    assert {h.doc_id for h in ans.hits} == {seeded["ai"], seeded["sec"]}
    assert not ans.not_found and ans.citations
    assert ans.llm.prompt_tokens > 0


def test_agent_multi_hop_path(seeded, use_llm):
    use_llm({"type": "multi_hop", "sub_questions": ["Which function is cross-cutting?", "What does it require?"]})
    ans = run_agent("Which function is cross-cutting and what does it require?", ["tenders"])
    nodes = [s["node"] for s in ans.steps]
    assert nodes == ["rewrite", "plan", "hop", "hop", "synthesize"]


def test_agent_invalid_plan_falls_back_to_simple(seeded, use_llm):
    use_llm({"type": "compare", "doc_a": None})  # compare with one doc → invalid → simple search
    llm = FakeLLM(scripted({"type": "nonsense"}))
    set_llm(llm)
    ans = run_agent("Which function is cross-cutting?", ["tenders"])
    assert [s["node"] for s in ans.steps] == ["rewrite", "plan", "search", "synthesize"]


def test_agent_not_found_when_no_evidence(seeded, use_llm):
    use_llm({"type": "simple"})
    ans = run_agent("zebra quantum pancake", [])
    assert ans.not_found and ans.answer == NOT_FOUND
