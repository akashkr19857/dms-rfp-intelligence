"use client";

import * as React from "react";
import { Bot, CircleSlash, Clock, Loader2, Send, Sparkles, Workflow } from "lucide-react";
import { api, getToken, WS_URL, type ChatResult, type Citation, type Doc, type Source, type Step } from "@/lib/api";
import { useAuth } from "@/components/auth";
import { AnswerText } from "@/components/answer-text";
import { SourceViewer } from "@/components/source-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/input";
import { cn, ms } from "@/lib/utils";

type Turn = {
  id: number;
  question: string;
  mode: "rag" | "agent";
  text: string;
  steps: Step[];
  sources: Source[];
  result?: ChatResult;
  error?: string;
  pending: boolean;
};

const SUGGESTIONS: Record<string, string[]> = {
  tenders: [
    "Which of our RFPs require hosting inside the United States?",
    "Compare the proposal submission requirements of the Champaign County and Detroit RFPs.",
  ],
  "knowledge-base": [
    "What certifications and security controls does our company have?",
    "How long does a typical implementation take for us, and what was our fastest?",
  ],
};

type Preview = { docId: number; page: number; chunkId: string; title: string; text?: string };

export default function AskPage() {
  const { user } = useAuth();
  const [workspace, setWorkspace] = React.useState("all");
  const [mode, setMode] = React.useState<"rag" | "agent">("rag");
  const [input, setInput] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [docs, setDocs] = React.useState<Doc[]>([]);
  const wsRef = React.useRef<WebSocket | null>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);

  React.useEffect(() => {
    api<Doc[]>("/api/documents").then(setDocs).catch(() => {});
  }, [user]);
  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);
  React.useEffect(() => () => wsRef.current?.close(), []);

  const update = (id: number, fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  const getSocket = (): Promise<WebSocket> =>
    new Promise((resolve, reject) => {
      const cur = wsRef.current;
      if (cur && cur.readyState === WebSocket.OPEN) return resolve(cur);
      const ws = new WebSocket(`${WS_URL}/ws/chat?token=${encodeURIComponent(getToken() ?? "")}`);
      ws.onopen = () => resolve(ws);
      ws.onerror = () => reject(new Error("WebSocket connection failed - is the API running on :8200?"));
      wsRef.current = ws;
    });

  const ask = async (q?: string) => {
    const question = (q ?? input).trim();
    if (!question || busy) return;
    setInput("");
    const id = Date.now();
    const history = turns
      .filter((t) => t.result)
      .slice(-2)
      .flatMap((t) => [
        { role: "user", content: t.question },
        { role: "assistant", content: t.result!.answer },
      ]);
    setTurns((ts) => [...ts, { id, question, mode, text: "", steps: [], sources: [], pending: true }]);
    try {
      const ws = await getSocket();
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        if (ev.type === "token") update(id, (t) => ({ ...t, text: t.text + ev.text }));
        else if (ev.type === "sources") update(id, (t) => ({ ...t, sources: ev.sources }));
        else if (ev.type === "step") update(id, (t) => ({ ...t, steps: [...t.steps, ev.step] }));
        else if (ev.type === "final") {
          const r: ChatResult = ev.result;
          update(id, (t) => ({ ...t, pending: false, result: r, text: r.answer, sources: r.sources, steps: r.steps.length ? r.steps : t.steps }));
          const first = r.citations[0];
          if (first) openCitation(r, first);
        } else if (ev.type === "error") update(id, (t) => ({ ...t, pending: false, error: String(ev.error) }));
      };
      ws.send(JSON.stringify({ question, mode, workspace, history }));
    } catch (e) {
      update(id, (t) => ({ ...t, pending: false, error: (e as Error).message }));
    }
  };

  const openCitation = (r: ChatResult, c: Citation) => setPreview({ docId: c.doc_id, page: c.page, chunkId: c.chunk_id, title: c.doc_title, text: r.sources.find((s) => s.chunk_id === c.chunk_id)?.text });
  const openSource = (s: Source) => setPreview({ docId: s.doc_id, page: s.page, chunkId: s.chunk_id, title: s.doc_title, text: s.text });
  const workspaces = user?.workspaces ?? [];
  const suggestions = (workspace === "all" ? workspaces : [workspace]).flatMap((w) => SUGGESTIONS[w] ?? []).slice(0, 4);
  const previewDoc = docs.find((d) => d.id === preview?.docId);

  return (
    <div className="grid h-[calc(100vh-7.5rem)] min-h-[560px] grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(340px,44%)]">
      <Card className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <Select value={workspace} onChange={(e) => setWorkspace(e.target.value)} aria-label="Workspace" data-testid="workspace-select">
            <option value="all">All my workspaces</option>
            {workspaces.map((w) => (
              <option key={w} value={w}>{w}</option>
            ))}
          </Select>
          <div className="flex rounded-md border p-0.5 text-sm" role="tablist">
            {(["rag", "agent"] as const).map((m) => (
              <button
                key={m}
                data-testid={`mode-${m}`}
                onClick={() => setMode(m)}
                className={cn("flex items-center gap-1 rounded px-3 py-1", mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent")}
              >
                {m === "rag" ? <Sparkles className="h-3.5 w-3.5" /> : <Workflow className="h-3.5 w-3.5" />}
                {m === "rag" ? "Answer" : "Agent"}
              </button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {mode === "rag" ? "Hybrid search + reranker → cited answer (streamed)" : "LangGraph: rewrite → plan → multi-hop / compare → answer"}
          </span>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {turns.length === 0 && (
            <div className="mx-auto mt-6 max-w-lg text-center">
              <Bot className="mx-auto h-10 w-10 text-primary" />
              <h2 className="mt-3 text-lg font-semibold">Ask your documents</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Answers come only from the RFPs and the knowledge base you can access, with page-level citations. If the documents don&apos;t say, the assistant says so.
              </p>
              <div className="mt-5 grid gap-2">
                {suggestions.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="rounded-md border p-2.5 text-left text-sm hover:border-primary hover:bg-accent">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t) => (
            <div key={t.id} className="space-y-2" data-testid="turn">
              <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{t.question}</div>
              {t.steps.length > 0 && (
                <div className="space-y-1 rounded-md border border-dashed p-2 text-xs" data-testid="agent-steps">
                  {t.steps.map((s, i) => (
                    <div key={i} className="flex gap-2">
                      <Badge variant="secondary" className="shrink-0">{s.node}</Badge>
                      <span className="min-w-0 text-muted-foreground">{s.detail}</span>
                      <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{ms(s.ms)}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="max-w-[95%] rounded-lg border bg-muted/40 p-3" data-testid="answer">
                {t.error ? (
                  <p className="text-sm text-destructive">{t.error}</p>
                ) : t.result?.not_found ? (
                  <div className="flex items-start gap-2 text-sm">
                    <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                    <span data-testid="not-found">{t.result.answer}</span>
                  </div>
                ) : t.text ? (
                  <AnswerText text={t.text} citations={t.result?.citations ?? []} onCite={(n) => {
                    const c = t.result?.citations.find((x) => x.n === n);
                    if (c && t.result) openCitation(t.result, c);
                  }} />
                ) : (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> {t.mode === "agent" ? "Agent is planning…" : "Searching documents…"}
                  </div>
                )}
                {t.result && (
                  <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-2 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3" /> {ms(t.result.latency_ms)}
                    <span>· retrieve {ms(t.result.retrieval_ms)}</span>
                    <span>· rerank {ms(t.result.rerank_ms)}</span>
                    <span>· LLM {ms(t.result.llm_ms)}</span>
                    <span>· {t.result.prompt_tokens + t.result.completion_tokens} tokens</span>
                    {t.result.citations.map((c) => (
                      <button key={c.n} onClick={() => openCitation(t.result!, c)} className="rounded border px-1.5 py-0.5 hover:border-primary hover:text-primary">
                        [{c.n}] {c.doc_title.slice(0, 28)} p.{c.page}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form
          className="flex items-end gap-2 border-t p-3"
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
        >
          <Textarea
            id="question"
            data-testid="question"
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
            placeholder="Ask a question about your documents…"
            className="resize-none"
          />
          <Button type="submit" disabled={busy || !input.trim()} data-testid="ask">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Ask
          </Button>
        </form>
      </Card>

      <div className="flex min-h-0 flex-col gap-4">
        <Card className="flex min-h-[340px] flex-[3] flex-col">
          <CardHeader className="pb-1">
            <CardTitle>Source preview</CardTitle>
          </CardHeader>
          <CardContent className="min-h-0 flex-1">
            {preview ? (
              <SourceViewer source={{ docId: preview.docId, page: preview.page, chunkId: preview.chunkId, title: preview.title, pages: previewDoc?.pages, fileType: previewDoc?.file_type, text: preview.text }} />
            ) : (
              <p className="text-sm text-muted-foreground">Click a citation to open the PDF page with the cited passage highlighted.</p>
            )}
          </CardContent>
        </Card>
        <Card className="flex min-h-0 flex-[2] flex-col">
          <CardHeader className="pb-1">
            <CardTitle>Retrieved chunks</CardTitle>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 space-y-2 overflow-y-auto" data-testid="sources">
            {(turns.at(-1)?.sources ?? []).map((s, i) => (
              <button
                key={s.chunk_id}
                onClick={() => openSource(s)}
                className={cn("w-full rounded-md border p-2 text-left text-xs hover:border-primary", preview?.chunkId === s.chunk_id && "border-primary bg-primary/5")}
              >
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold">[{i + 1}]</span>
                  <span className="truncate font-medium">{s.doc_title}</span>
                  <span className="shrink-0 text-muted-foreground">p.{s.page}</span>
                  {s.kind !== "text" && <Badge variant="warning">{s.kind}</Badge>}
                  {s.rerank_score !== null && <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">rerank {s.rerank_score.toFixed(3)}</span>}
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  BM25 #{s.bm25_rank ?? "–"} · vector #{s.vector_rank ?? "–"}
                  {s.section && ` · ${s.section.slice(0, 60)}`}
                </div>
                <p className="mt-1 line-clamp-3 text-muted-foreground">{s.text}</p>
              </button>
            ))}
            {!turns.length && <p className="text-sm text-muted-foreground">Chunks used for the last answer show here with their BM25, vector and reranker scores.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
