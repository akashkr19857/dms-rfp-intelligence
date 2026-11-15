"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle, ArrowLeft, BookOpen, CalendarClock, ClipboardCheck, Download, FileSignature, Gauge, Loader2, MessageSquare,
  RefreshCw, Search, Send, Sparkles,
} from "lucide-react";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  api, eventsSocket, fileUrl, type Analysis, type BidScore, type ChatResult, type KbSource, type Proposal, type Requirement, type Risk,
  type TenderSummary,
} from "@/lib/api";
import { useAuth } from "@/components/auth";
import { AnswerText } from "@/components/answer-text";
import { SourceViewer, type SourceRef } from "@/components/source-viewer";
import { AnalysisProgress, STATUS_META, ScoreGauge, SeverityBadge, StatusBadge, StatusBar, recColor } from "@/components/tender-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/input";
import { cn, ms } from "@/lib/utils";

type Tab = "overview" | "requirements" | "risks" | "proposal" | "ask";
const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "requirements", label: "Requirements & compliance", icon: ClipboardCheck },
  { id: "risks", label: "Risks & gaps", icon: AlertTriangle },
  { id: "proposal", label: "Proposal draft", icon: FileSignature },
  { id: "ask", label: "Ask this RFP", icon: MessageSquare },
];

const FACT_LABELS: [string, string][] = [
  ["issuer", "Issuer"], ["rfp_number", "Solicitation no."], ["submission_deadline", "Proposal due"], ["questions_deadline", "Questions deadline"],
  ["pre_proposal_meeting", "Pre-proposal meeting"], ["contact", "Contact"], ["submission_method", "Submission method"], ["budget", "Budget"],
  ["contract_term", "Contract"], ["proposal_validity", "Proposal validity"], ["deployment_model", "Deployment"], ["target_go_live", "Timeline"],
  ["scope_summary", "Scope"],
];

function PageLink({ page, onClick, label }: { page: number | null | undefined; onClick: () => void; label?: string }) {
  if (!page) return null;
  return (
    <button onClick={onClick} data-testid="page-link"
      className="inline-flex items-center rounded bg-primary/12 px-1.5 py-0.5 text-[11px] font-semibold text-primary hover:bg-primary hover:text-primary-foreground">
      {label ?? `p. ${page}`}
    </button>
  );
}

export default function TenderPage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);
  const { user } = useAuth();
  const [summary, setSummary] = React.useState<TenderSummary | null>(null);
  const [reqs, setReqs] = React.useState<Requirement[]>([]);
  const [risks, setRisks] = React.useState<Risk[]>([]);
  const [proposal, setProposal] = React.useState<Proposal | null>(null);
  const [tab, setTab] = React.useState<Tab>("overview");
  const [source, setSource] = React.useState<SourceRef | null>(null);
  const [error, setError] = React.useState("");
  const hasKb = user?.workspaces.includes("knowledge-base");

  const loadAll = React.useCallback(async () => {
    try {
      const s = await api<TenderSummary>(`/api/tenders/${docId}`);
      setSummary(s);
      if (s.analysis?.status === "done") {
        const [r, k, p] = await Promise.all([
          api<Requirement[]>(`/api/tenders/${docId}/requirements`),
          api<Risk[]>(`/api/tenders/${docId}/risks`),
          api<Proposal | null>(`/api/tenders/${docId}/proposal`),
        ]);
        setReqs(r);
        setRisks(k);
        setProposal(p);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [docId]);

  React.useEffect(() => {
    loadAll();
    return eventsSocket((ev) => {
      if (ev.type === "analysis") {
        const a = ev.analysis as Analysis;
        if (a.doc_id !== docId) return;
        setSummary((s) => (s ? { ...s, analysis: a } : s));
        if (a.status === "done") loadAll();
      } else if (ev.type === "proposal") {
        const p = ev.proposal as Proposal;
        if (p.doc_id === docId) setProposal(p);
      }
    });
  }, [docId, loadAll]);

  const doc = summary?.document;
  const a = summary?.analysis;
  const showRfp = (page: number | null | undefined, chunkId?: string | null) =>
    page && doc && setSource({ docId: doc.id, page, chunkId: chunkId ?? undefined, title: doc.title, fileType: doc.file_type, pages: doc.pages });
  const showKb = (k: KbSource) => setSource({ docId: k.doc_id, page: k.page, chunkId: k.chunk_id, title: k.doc_title, fileType: k.file_type, text: k.text });

  const reanalyze = async () => {
    setError("");
    await api(`/api/tenders/${docId}/analyze`, { method: "POST" }).catch((e) => setError(e.message));
  };

  if (!summary || !doc) return <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading… {error}</div>;
  const running = a && (a.status === "running" || a.status === "queued");
  const score = a?.status === "done" && a.bid_score && "score" in a.bid_score ? (a.bid_score as BidScore) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <Link href="/" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3 w-3" /> All tenders</Link>
          <h1 className="text-xl font-semibold" data-testid="tender-title">{doc.title}</h1>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">{doc.file_type.toUpperCase()} · {doc.pages} pages · {doc.n_chunks} chunks</Badge>
            {a?.status === "done" && <span>Analysed in {a.timings.total ?? "–"} s · {a.llm_calls} local LLM calls</span>}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={reanalyze} disabled={!!running || doc.status !== "ready"} data-testid="reanalyze">
          <RefreshCw className={cn("h-4 w-4", running && "animate-spin")} /> {a ? "Re-run analysis" : "Analyse"}
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {running && <Card><CardContent className="pt-4"><AnalysisProgress a={a!} /></CardContent></Card>}

      <div className="flex gap-1 overflow-x-auto border-b" role="tablist">
        {TABS.map(({ id: t, label, icon: Icon }) => (
          <button key={t} role="tab" aria-selected={tab === t} data-testid={`tab-${t}`} onClick={() => setTab(t)}
            className={cn("flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
              tab === t ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>
            <Icon className="h-4 w-4" />{label}
            {t === "requirements" && reqs.length > 0 && <Badge variant="secondary">{reqs.length}</Badge>}
            {t === "risks" && risks.length > 0 && <Badge variant={risks.some((r) => r.severity === "high") ? "destructive" : "secondary"}>{risks.length}</Badge>}
          </button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0">
          {a?.status !== "done" && tab !== "ask" ? (
            <Card><CardContent className="pt-4 text-sm text-muted-foreground">{running ? "Analysis in progress; results appear here when it finishes." : "Run the analysis to see results."}</CardContent></Card>
          ) : tab === "overview" ? (
            <Overview a={a!} score={score} reqs={reqs} risks={risks} showRfp={showRfp} />
          ) : tab === "requirements" ? (
            <Requirements reqs={reqs} setReqs={setReqs} showRfp={showRfp} showKb={showKb} />
          ) : tab === "risks" ? (
            <Risks risks={risks} reqs={reqs} showRfp={showRfp} showKb={showKb} />
          ) : tab === "proposal" ? (
            <ProposalTab docId={docId} proposal={proposal} setProposal={setProposal} hasKb={!!hasKb} showKb={showKb} showRfp={showRfp} />
          ) : (
            <Ask docId={docId} hasKb={!!hasKb} onSource={setSource} />
          )}
        </div>
        <Card className="flex h-[680px] flex-col xl:sticky xl:top-4">
          <CardHeader className="pb-1"><CardTitle className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-primary" />Source</CardTitle></CardHeader>
          <CardContent className="min-h-0 flex-1"><SourceViewer source={source} /></CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- overview
function Overview({ a, score, reqs, risks, showRfp }: { a: Analysis; score: BidScore | null; reqs: Requirement[]; risks: Risk[]; showRfp: (p: number | null, c?: string | null) => void }) {
  const byCat = Object.entries(reqs.reduce<Record<string, number>>((m, r) => ({ ...m, [r.category]: (m[r.category] ?? 0) + 1 }), {}))
    .map(([category, n]) => ({ category, n })).sort((x, y) => y.n - x.n);
  const statusData = ["met", "partial", "gap", "unknown"].map((s) => ({ name: STATUS_META[s].label, value: reqs.filter((r) => r.kind === "capability" && r.status === s).length, color: STATUS_META[s].color })).filter((d) => d.value);
  const checklist = reqs.filter((r) => r.kind === "submission").length;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card>
          <CardHeader><CardTitle>Bid / no-bid</CardTitle><CardDescription>Compliance with mandatory requirements and risk exposure</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {score && <ScoreGauge score={score} />}
            {score && (
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-md bg-muted/60 p-2"><dt className="text-muted-foreground">Compliance</dt><dd className="text-base font-semibold">{score.compliance_pct}%</dd></div>
                <div className="rounded-md bg-muted/60 p-2"><dt className="text-muted-foreground">Risk exposure</dt><dd className="text-base font-semibold">{score.risk_exposure}</dd></div>
                <div className="rounded-md bg-muted/60 p-2"><dt className="text-muted-foreground">Mandatory reqs</dt><dd className="text-base font-semibold">{score.mandatory_total}</dd></div>
                <div className="rounded-md bg-muted/60 p-2"><dt className="text-muted-foreground">High risks</dt><dd className={cn("text-base font-semibold", score.high_risks && "text-destructive")}>{score.high_risks}</dd></div>
              </dl>
            )}
            {score && <p className="text-[11px] leading-snug text-muted-foreground" title={score.method}>Score = 70% weighted compliance + 30% (100 − risk exposure). Hover for details.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Key facts</CardTitle><CardDescription>Extracted from the RFP; click a page to verify</CardDescription></CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2" data-testid="key-facts">
              {FACT_LABELS.map(([k, label]) => {
                const f = a.facts[k];
                if (!f?.value) return null;
                return (
                  <div key={k} className={cn("min-w-0", k === "scope_summary" && "sm:col-span-2")}>
                    <dt className="flex items-center gap-1 text-xs text-muted-foreground">{k === "submission_deadline" && <CalendarClock className="h-3 w-3 text-primary" />}{label}</dt>
                    <dd className="flex items-start gap-1.5"><span className="min-w-0">{f.value}</span><PageLink page={f.page} onClick={() => showRfp(f.page, f.chunk_id)} /></dd>
                  </div>
                );
              })}
            </dl>
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Compliance</CardTitle><CardDescription>{reqs.filter((r) => r.kind === "capability").length} capability requirements · {checklist} submission checklist items</CardDescription></CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={2}>
                  {statusData.map((d) => <Cell key={d.name} fill={d.color} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Requirements by category</CardTitle></CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer>
              <BarChart data={byCat} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="category" width={96} interval={0} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <Tooltip cursor={{ fill: "hsl(var(--muted))" }} />
                <Bar dataKey="n" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Top risks</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {risks.slice(0, 4).map((r) => (
              <button key={r.id} onClick={() => showRfp(r.page, r.chunk_id)} className="flex w-full items-start gap-2 rounded-md border p-2 text-left text-sm hover:bg-accent">
                <SeverityBadge severity={r.severity} /><span className="min-w-0 flex-1">{r.title}</span><span className="text-[11px] text-muted-foreground">p. {r.page}</span>
              </button>
            ))}
            {!risks.length && <p className="text-sm text-muted-foreground">No risks found.</p>}
          </CardContent>
        </Card>
      </div>
      {a.evaluation_criteria.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Evaluation criteria</CardTitle><CardDescription>How proposals will be scored</CardDescription></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 pr-3">Criterion</th><th className="py-1 pr-3">Weight</th><th className="py-1 pr-3">Stage</th><th className="py-1">Source</th></tr></thead>
              <tbody>
                {a.evaluation_criteria.map((c, i) => (
                  <tr key={i} className="border-t"><td className="py-1.5 pr-3">{c.criterion}</td><td className="py-1.5 pr-3 font-medium tabular-nums">{c.weight ?? "–"}</td><td className="py-1.5 pr-3 text-muted-foreground">{c.stage ?? "–"}</td><td className="py-1.5"><PageLink page={c.page} onClick={() => showRfp(c.page, c.chunk_id)} /></td></tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle>Analysis timing</CardTitle><CardDescription>Measured on this machine with local models</CardDescription></CardHeader>
        <CardContent className="flex flex-wrap gap-2 text-xs">
          {Object.entries(a.timings).map(([k, v]) => <Badge key={k} variant={k === "total" ? "default" : "outline"}>{k}: {v}s</Badge>)}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- requirements & compliance
function Requirements({ reqs, setReqs, showRfp, showKb }: { reqs: Requirement[]; setReqs: React.Dispatch<React.SetStateAction<Requirement[]>>; showRfp: (p: number | null, c?: string | null) => void; showKb: (k: KbSource) => void }) {
  const [status, setStatus] = React.useState("all");
  const [category, setCategory] = React.useState("all");
  const [q, setQ] = React.useState("");
  const [mandatoryOnly, setMandatoryOnly] = React.useState(false);
  const cats = Array.from(new Set(reqs.map((r) => r.category))).sort();
  const counts = reqs.reduce<Record<string, number>>((m, r) => ({ ...m, [r.status]: (m[r.status] ?? 0) + 1 }), {});
  const shown = reqs.filter((r) => (status === "all" || r.status === status) && (category === "all" || r.category === category)
    && (!mandatoryOnly || r.mandatory) && (!q || r.text.toLowerCase().includes(q.toLowerCase())));

  const override = async (r: Requirement, s: string) => {
    const updated = await api<Requirement>(`/api/requirements/${r.id}`, { method: "PATCH", body: JSON.stringify({ status: s }) });
    setReqs((rs) => rs.map((x) => (x.id === r.id ? updated : x)));
  };

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div><CardTitle>Compliance matrix</CardTitle><CardDescription>Every requirement the RFP places on the bidder, checked against your knowledge base. Override any status after review.</CardDescription></div>
        <StatusBar counts={counts} />
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input className="w-56 pl-8" placeholder="Search requirements" value={q} onChange={(e) => setQ(e.target.value)} data-testid="req-search" /></div>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status" data-testid="status-filter">
            <option value="all">All statuses</option>
            {["met", "partial", "gap", "unknown", "action"].map((s) => <option key={s} value={s}>{STATUS_META[s].label} ({counts[s] ?? 0})</option>)}
          </Select>
          <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter by category">
            <option value="all">All categories</option>
            {cats.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
          <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={mandatoryOnly} onChange={(e) => setMandatoryOnly(e.target.checked)} />Mandatory only</label>
          <span className="text-xs text-muted-foreground">{shown.length} shown</span>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm" data-testid="req-table">
          <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
            <tr><th className="p-2 pl-4">Ref</th><th className="p-2">Requirement</th><th className="p-2">Type</th><th className="p-2">Status</th><th className="p-2">Evidence from knowledge base</th></tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="p-2 pl-4 font-mono text-xs text-muted-foreground">{r.ref}</td>
                <td className="max-w-[420px] p-2">
                  <div>{r.text}</div>
                  <div className="mt-1"><PageLink page={r.page} onClick={() => showRfp(r.page, r.chunk_id)} label={`RFP p. ${r.page}`} /></div>
                </td>
                <td className="p-2"><div className="flex flex-col gap-1"><Badge variant="outline">{r.category}</Badge>{r.mandatory ? <Badge variant="secondary">mandatory</Badge> : <Badge variant="outline">desirable</Badge>}</div></td>
                <td className="p-2">
                  <div className="flex flex-col gap-1">
                    <StatusBadge status={r.status} />
                    <select aria-label={`Override status for ${r.ref}`} value="" onChange={(e) => e.target.value && override(r, e.target.value)} className="rounded border bg-card px-1 text-[11px] text-muted-foreground">
                      <option value="">override…</option>
                      {["met", "partial", "gap", "unknown", "action"].map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
                    </select>
                  </div>
                </td>
                <td className="max-w-[360px] p-2 text-xs">
                  <div className="text-muted-foreground">{r.evidence}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {r.kb_sources.map((k) => <PageLink key={k.chunk_id} page={k.page} onClick={() => showKb(k)} label={`${k.doc_title.replace(" (Nimbus, fictional)", "")} · ${k.file_type === "docx" ? "part" : "p."} ${k.page}`} />)}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- risks & gaps
function Risks({ risks, reqs, showRfp, showKb }: { risks: Risk[]; reqs: Requirement[]; showRfp: (p: number | null, c?: string | null) => void; showKb: (k: KbSource) => void }) {
  const gaps = reqs.filter((r) => r.status === "gap" || r.status === "partial");
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Risk register</CardTitle><CardDescription>RFP clauses compared with your standard terms and capabilities</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2" data-testid="risk-list">
          {risks.map((r) => (
            <div key={r.id} className={cn("space-y-2 rounded-lg border p-3", r.severity === "high" && "border-destructive/50 bg-destructive/5")}>
              <div className="flex items-start justify-between gap-2"><div className="font-medium">{r.title}</div><SeverityBadge severity={r.severity} /></div>
              <p className="text-sm text-muted-foreground">{r.description}</p>
              {r.recommendation && <p className="text-sm"><span className="font-medium">Recommendation: </span>{r.recommendation}</p>}
              <div className="flex flex-wrap items-center gap-1">
                <Badge variant="outline">{r.category}</Badge>
                <PageLink page={r.page} onClick={() => showRfp(r.page, r.chunk_id)} label={`RFP p. ${r.page}`} />
                {r.kb_sources.map((k) => <PageLink key={k.chunk_id} page={k.page} onClick={() => showKb(k)} label={`${k.doc_title.replace(" (Nimbus, fictional)", "")}`} />)}
              </div>
            </div>
          ))}
          {!risks.length && <p className="text-sm text-muted-foreground">No risks found.</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Capability gaps</CardTitle><CardDescription>{gaps.length} requirements we do not fully meet; address them in the proposal or with a partner</CardDescription></CardHeader>
        <CardContent className="space-y-2">
          {gaps.map((r) => (
            <div key={r.id} className="flex flex-wrap items-start gap-2 rounded-md border p-2 text-sm">
              <StatusBadge status={r.status} />
              <div className="min-w-0 flex-1"><div>{r.text}</div><div className="text-xs text-muted-foreground">{r.evidence}</div></div>
              <PageLink page={r.page} onClick={() => showRfp(r.page, r.chunk_id)} label={`RFP p. ${r.page}`} />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- proposal
function ProposalText({ text, onCite }: { text: string; onCite: (label: string) => void }) {
  const parts = text.split(/(\[[RK]\d{1,2}\]|\[Bid team to confirm:[^\]]*\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((p, i) => {
        if (/^\[[RK]\d{1,2}\]$/.test(p)) {
          const label = p.slice(1, -1);
          return <button key={i} onClick={() => onCite(label)} className={cn("mx-0.5 rounded px-1 text-[11px] font-semibold", label.startsWith("K") ? "bg-success/15 text-success" : "bg-primary/15 text-primary")}>{label}</button>;
        }
        if (p.startsWith("[Bid team to confirm")) return <mark key={i} className="rounded bg-warning/20 px-1 text-foreground">{p}</mark>;
        return <React.Fragment key={i}>{p}</React.Fragment>;
      })}
    </p>
  );
}

function ProposalTab({ docId, proposal, setProposal, hasKb, showKb, showRfp }: { docId: number; proposal: Proposal | null; setProposal: (p: Proposal) => void; hasKb: boolean; showKb: (k: KbSource) => void; showRfp: (p: number | null, c?: string | null) => void }) {
  const [error, setError] = React.useState("");
  const start = async () => {
    setError("");
    try {
      setProposal(await api<Proposal>(`/api/tenders/${docId}/proposal`, { method: "POST" }));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const running = proposal?.status === "running";
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
        <div><CardTitle>Proposal response draft</CardTitle><CardDescription>Written section by section from your knowledge base. <span className="text-success">K</span> = knowledge-base source, <span className="text-primary">R</span> = RFP source; yellow = needs your input.</CardDescription></div>
        <div className="flex gap-2">
          {proposal?.status === "done" && <Button asChild variant="outline" size="sm"><a href={fileUrl(`/api/proposals/${proposal.id}/docx`)} data-testid="download-docx"><Download className="h-4 w-4" /> Download DOCX</a></Button>}
          <Button size="sm" onClick={start} disabled={running || !hasKb} data-testid="generate-proposal">{running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{proposal ? "Regenerate" : "Generate draft"}</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {!hasKb && <p className="text-sm text-muted-foreground">Your role cannot access the knowledge base, so it cannot draft proposals.</p>}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {running && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Writing section {(proposal?.sections.length ?? 0) + 1} of 8…</p>}
        {proposal?.sections.map((s) => (
          <section key={s.key} className="space-y-1.5" data-testid="proposal-section">
            <h3 className="flex items-center justify-between gap-2 font-semibold">{s.title}<span className="text-[11px] font-normal text-muted-foreground">{ms(s.ms)}</span></h3>
            <ProposalText text={s.text} onCite={(label) => {
              const c = s.citations.find((x) => x.label === label);
              if (!c) return;
              if (label.startsWith("K")) showKb(c);
              else showRfp(c.page, c.chunk_id);
            }} />
          </section>
        ))}
        {!proposal && hasKb && <p className="text-sm text-muted-foreground">Generate a first draft: executive summary, experience, solution, approach, data conversion, security, personnel and exceptions, plus a compliance matrix and risk register in the Word export.</p>}
        {proposal?.status === "failed" && <p className="text-sm text-destructive">{proposal.error}</p>}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- ask
const ASK_SUGGESTIONS = [
  "When are proposals due and how must they be submitted?",
  "What deployment and hosting options are acceptable?",
  "Do we meet the disaster recovery and data backup requirements?",
  "What happens to the data when the contract ends?",
];

function Ask({ docId, hasKb, onSource }: { docId: number; hasKb: boolean; onSource: (s: SourceRef) => void }) {
  const [q, setQ] = React.useState("");
  const [turns, setTurns] = React.useState<{ q: string; r?: ChatResult; error?: string }[]>([]);
  const [busy, setBusy] = React.useState(false);
  const ask = async (question?: string) => {
    const text = (question ?? q).trim();
    if (!text || busy) return;
    setQ("");
    setBusy(true);
    setTurns((t) => [...t, { q: text }]);
    try {
      const r = await api<ChatResult>("/api/chat", { method: "POST", body: JSON.stringify({ question: text, mode: "rag", tender_id: docId }) });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, r } : x)));
      const c = r.citations[0];
      const s = c && r.sources.find((x) => x.chunk_id === c.chunk_id);
      if (c) onSource({ docId: c.doc_id, page: c.page, chunkId: c.chunk_id, title: c.doc_title, fileType: s?.file_type, text: s?.text });
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="flex min-h-[560px] flex-col">
      <CardHeader><CardTitle>Ask this RFP{hasKb ? " + knowledge base" : ""}</CardTitle><CardDescription>Grounded answers with page citations, or an explicit &quot;not found&quot;.</CardDescription></CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex-1 space-y-4 overflow-y-auto" data-testid="ask-thread">
          {!turns.length && (
            <div className="flex flex-wrap gap-2">
              {ASK_SUGGESTIONS.map((s) => <Button key={s} variant="outline" size="sm" className="h-auto whitespace-normal py-1.5 text-left" onClick={() => ask(s)}>{s}</Button>)}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{t.q}</div>
              {t.error ? <p className="text-sm text-destructive">{t.error}</p> : t.r ? (
                <div className="space-y-1 rounded-lg border p-3" data-testid="ask-answer">
                  <AnswerText text={t.r.answer} citations={t.r.citations} onCite={(n) => {
                    const c = t.r!.citations.find((x) => x.n === n);
                    const s = c && t.r!.sources.find((x) => x.chunk_id === c.chunk_id);
                    if (c) onSource({ docId: c.doc_id, page: c.page, chunkId: c.chunk_id, title: c.doc_title, fileType: s?.file_type, text: s?.text });
                  }} />
                  <div className="text-[11px] text-muted-foreground">{ms(t.r.latency_ms)} · {t.r.citations.length} citations</div>
                </div>
              ) : <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Searching the RFP{hasKb ? " and knowledge base" : ""}…</p>}
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Textarea rows={2} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What insurance does the RFP require?" data-testid="ask-input"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
          <Button onClick={() => ask()} disabled={busy || !q.trim()} aria-label="Ask" data-testid="ask-send"><Send className="h-4 w-4" /></Button>
        </div>
      </CardContent>
    </Card>
  );
}
