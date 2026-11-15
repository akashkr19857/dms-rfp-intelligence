from __future__ import annotations

import io

from conftest import auth

from app.llm import FakeLLM, set_llm


def test_health_and_login(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.post("/api/login", json={"user_id": "reviewer"})
    assert r.status_code == 200 and r.json()["token"] == "demo-reviewer"
    assert client.post("/api/login", json={"user_id": "mallory"}).status_code == 404


def test_auth_required(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/me", headers=auth("kbuser")).json()["workspaces"] == ["knowledge-base"]


def test_documents_are_scoped_to_workspaces(client, seeded):
    titles = {d["title"] for d in client.get("/api/documents", headers=auth("reviewer")).json()}
    assert titles == {"AI Risk Test Doc"}
    assert len(client.get("/api/documents", headers=auth("bid-manager")).json()) == 2
    assert client.get("/api/documents?workspace=knowledge-base", headers=auth("reviewer")).status_code == 403
    # direct access to another workspace's document is hidden as 404
    assert client.get(f"/api/documents/{seeded['sec']}/chunks", headers=auth("reviewer")).status_code == 404
    assert client.get(f"/api/documents/{seeded['sec']}/pages/1.png?token=demo-reviewer").status_code == 404


def test_page_image_with_highlight(client, seeded):
    chunks = client.get(f"/api/documents/{seeded['ai']}/chunks?page=1", headers=auth("reviewer")).json()
    r = client.get(f"/api/documents/{seeded['ai']}/pages/1.png", params={"token": "demo-reviewer", "chunk_id": chunks[0]["id"]})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{seeded['ai']}/pages/99.png?token=demo-reviewer").status_code == 404


def test_chat_rag_records_trace_and_usage(client):
    set_llm(FakeLLM(lambda m: "MFA should be enabled on all accounts [1]."))
    try:
        r = client.post("/api/chat", headers=auth("kbuser"), json={"question": "Should we enable multi-factor authentication?"})
    finally:
        set_llm(None)
    body = r.json()
    assert r.status_code == 200 and not body["not_found"]
    assert body["citations"][0]["doc_title"] == "Security Test Doc"
    assert body["trace_id"] and body["sources"]
    traces = client.get("/api/traces", headers=auth("kbuser")).json()
    assert traces[0]["id"] == body["trace_id"] and traces[0]["chunks"]
    usage = client.get("/api/usage", headers=auth("kbuser")).json()
    assert usage["queries"] >= 1 and usage["p95_ms"] >= usage["p50_ms"]
    # members cannot see other users' traces
    assert all(t["user_id"] == "reviewer" for t in client.get("/api/traces", headers=auth("reviewer")).json())


def test_chat_forbidden_workspace(client):
    r = client.post("/api/chat", headers=auth("reviewer"), json={"question": "MFA?", "workspace": "knowledge-base"})
    assert r.status_code == 403


def test_websocket_chat_streams_events(client):
    set_llm(FakeLLM(lambda m: "Back up data and verify backups [1]."))
    try:
        with client.websocket_connect("/ws/chat?token=demo-kbuser") as ws:
            ws.send_json({"question": "How should backups be handled?", "mode": "rag"})
            types = []
            while True:
                ev = ws.receive_json()
                types.append(ev["type"])
                if ev["type"] in ("final", "error"):
                    break
    finally:
        set_llm(None)
    assert types[0] == "sources" and "token" in types and types[-1] == "final"


def test_upload_validation(client):
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    assert client.post("/api/documents", headers=auth("reviewer"), files=files, data={"workspace": "tenders"}).status_code == 400
    files = {"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}
    assert client.post("/api/documents", headers=auth("reviewer"), files=files, data={"workspace": "tenders"}).status_code == 400
    files = {"file": ("x.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    assert client.post("/api/documents", headers=auth("reviewer"), files=files, data={"workspace": "knowledge-base"}).status_code == 403


def test_eval_endpoints_empty_ok(client):
    assert client.get("/api/eval/runs", headers=auth("bid-manager")).status_code == 200
    assert client.get("/api/eval/runs/9999", headers=auth("bid-manager")).status_code == 404
