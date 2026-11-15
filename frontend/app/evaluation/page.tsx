"use client";

import * as React from "react";
import { CheckCircle2, Cpu, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { cn, ms, pct } from "@/lib/utils";

type Metrics = {
  facts: { accuracy: number; n: number };
  requirements: { recall: number; n: number; extracted_total: number; capability: number; submission: number };
  compliance: { accuracy: number | null; judged: number; n: number };
  risks: { recall: number; n: number; detected_total: number; high: number };
  qa: { correctness: number; fully_correct: number; "retrieval_hit@5": number; not_found_accuracy: number; false_refusals: number; latency_p50_ms: number; latency_p95_ms: number; n: number } | Record<string, never>;
  analysis: { doc: string; pages: number; chunks: number; seconds: number; llm_calls: number; requirements: number; risks: number; bid_score: number; recommendation: string }[];
};
type Run = { id: number; release: string; label: string; metrics: Metrics; hardware: string; created_at: string };
type Details = {
  facts: { doc: string; field: string; value: string; correct: boolean }[];
  requirements: { id: string; page: number; found: boolean; match: string | null; match_ref: string | null }[];
  compliance: { id: string; expected: string[]; predicted: string | null; correct: boolean | null; requirement?: string; evidence?: string }[];
  risks: { id: string; found: boolean; match: string | null; severity: string | null }[];
  qa: { id: string; question: string; reference: string; answer: string; score: number; reason: string; "hit@5": boolean | null; latency_ms: number }[];
};

function Mark({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-muted-foreground">–</span>;
  return ok ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-destructive" />;
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3" data-testid="eval-metric">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function EvaluationPage() {
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [runId, setRunId] = React.useState<number | null>(null);
  const [details, setDetails] = React.useState<Details | null>(null);
  React.useEffect(() => {
    api<Run[]>("/api/eval/runs").then((r) => {
      setRuns(r);
      if (r.length) setRunId(r[r.length - 1].id);
    });
  }, []);
  React.useEffect(() => {
    if (runId) api<{ details: Details }>(`/api/eval/runs/${runId}`).then((r) => setDetails(r.details));
  }, [runId]);
  const run = runs.find((r) => r.id === runId);
  if (!runs.length) return <p className="text-sm text-muted-foreground">No evaluation runs yet. Run <code>python backend/eval/run_eval.py</code>.</p>;
  if (!run) return null;
  const m = run.metrics;
  const qa = m.qa as Exclude<Metrics["qa"], Record<string, never>>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Evaluation</h1>
          <p className="text-sm text-muted-foreground">Measured against a hand-labelled answer key from the real RFP text. Nothing here is estimated.</p>
        </div>
        <Select value={runId ?? undefined} onChange={(e) => setRunId(Number(e.target.value))} aria-label="Evaluation run">
          {runs.map((r) => <option key={r.id} value={r.id}>{r.release} · {r.label} · {new Date(r.created_at).toLocaleString()}</option>)}
        </Select>
      </div>
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><Cpu className="h-3.5 w-3.5" />{run.hardware}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Key-fact accuracy" value={pct(m.facts.accuracy, 0)} sub={`${m.facts.n} labelled fields, 2 RFPs`} />
        <Metric label="Requirement recall" value={pct(m.requirements.recall, 0)} sub={`${m.requirements.n} labelled · ${m.requirements.extracted_total} extracted in total`} />
        <Metric label="Compliance accuracy" value={pct(m.compliance.accuracy, 0)} sub={`${m.compliance.judged} of ${m.compliance.n} labelled statuses judged`} />
        <Metric label="Risk recall" value={pct(m.risks.recall, 0)} sub={`${m.risks.n} labelled · ${m.risks.detected_total} detected (${m.risks.high} high)`} />
        {qa?.n ? (
          <>
            <Metric label="Q&A correctness" value={pct(qa.correctness, 0)} sub={`LLM judge, ${qa.n - 1} answerable questions`} />
            <Metric label="Retrieval hit@5" value={pct(qa["retrieval_hit@5"], 0)} sub="gold page in top 5 sources" />
            <Metric label="Not-found handling" value={pct(qa.not_found_accuracy, 0)} sub={`${qa.false_refusals} false refusals`} />
            <Metric label="Answer latency" value={ms(qa.latency_p50_ms)} sub={`p95 ${ms(qa.latency_p95_ms)}`} />
          </>
        ) : null}
      </div>
      <Card>
        <CardHeader><CardTitle>Full analysis per RFP</CardTitle><CardDescription>Wall-clock time for facts, requirements, compliance, risks and score</CardDescription></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 pr-3">RFP</th><th className="pr-3">Pages</th><th className="pr-3">Time</th><th className="pr-3">LLM calls</th><th className="pr-3">Requirements</th><th className="pr-3">Risks</th><th>Bid score</th></tr></thead>
            <tbody>
              {m.analysis.map((a) => (
                <tr key={a.doc} className="border-t"><td className="py-1.5 pr-3">{a.doc}</td><td className="pr-3 tabular-nums">{a.pages}</td><td className="pr-3 tabular-nums">{a.seconds}s</td><td className="pr-3 tabular-nums">{a.llm_calls}</td><td className="pr-3 tabular-nums">{a.requirements}</td><td className="pr-3 tabular-nums">{a.risks}</td><td>{a.bid_score} · {a.recommendation}</td></tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {details && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Requirement recall (Champaign County)</CardTitle></CardHeader>
            <CardContent className="max-h-96 space-y-1 overflow-y-auto text-sm">
              {details.requirements.map((r) => (
                <div key={r.id} className="flex items-start gap-2 border-t py-1"><Mark ok={r.found} /><span className="w-32 shrink-0 font-mono text-xs">{r.id}</span><span className="text-xs text-muted-foreground">p.{r.page} {r.match_ref ? `→ ${r.match_ref}: ${r.match}` : "not extracted"}</span></div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Compliance status vs answer key</CardTitle></CardHeader>
            <CardContent className="max-h-96 space-y-1 overflow-y-auto text-sm">
              {details.compliance.map((c) => (
                <div key={c.id} className="flex items-start gap-2 border-t py-1">
                  <Mark ok={c.correct} /><span className="w-32 shrink-0 font-mono text-xs">{c.id}</span>
                  <span className="text-xs">expected <b>{c.expected.join("/")}</b> · got <b className={cn(c.correct === false && "text-destructive")}>{c.predicted ?? "not extracted"}</b></span>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Key facts</CardTitle></CardHeader>
            <CardContent className="max-h-96 space-y-1 overflow-y-auto text-sm">
              {details.facts.map((f, i) => (
                <div key={i} className="flex items-start gap-2 border-t py-1"><Mark ok={f.correct} /><span className="w-44 shrink-0 text-xs"><Badge variant="secondary">{f.doc.split("_")[0]}</Badge> {f.field}</span><span className="text-xs text-muted-foreground">{f.value || "(empty)"}</span></div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Risks</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-sm">
              {details.risks.map((r) => (
                <div key={r.id} className="flex items-start gap-2 border-t py-1"><Mark ok={r.found} /><span className="w-36 shrink-0 font-mono text-xs">{r.id}</span><span className="text-xs text-muted-foreground">{r.match ? `${r.match} (${r.severity})` : "not detected"}</span></div>
              ))}
            </CardContent>
          </Card>
          {details.qa.length > 0 && (
            <Card className="xl:col-span-2">
              <CardHeader><CardTitle>Grounded Q&amp;A</CardTitle></CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground"><tr><th className="py-1 pr-2">Question</th><th className="pr-2">Answer</th><th className="pr-2">Score</th><th className="pr-2">Hit@5</th><th>Latency</th></tr></thead>
                  <tbody>
                    {details.qa.map((q) => (
                      <tr key={q.id} className="border-t align-top">
                        <td className="max-w-xs py-1.5 pr-2">{q.question}<div className="text-muted-foreground">Ref: {q.reference}</div></td>
                        <td className="max-w-md pr-2">{q.answer}</td>
                        <td className="pr-2 font-semibold tabular-nums" title={q.reason}>{q.score}</td>
                        <td className="pr-2"><Mark ok={q["hit@5"]} /></td>
                        <td className="tabular-nums">{ms(q.latency_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
