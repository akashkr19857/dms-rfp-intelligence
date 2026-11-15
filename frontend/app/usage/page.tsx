"use client";

import * as React from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ChevronDown, ChevronRight, CircleSlash, Coins, Gauge, Timer } from "lucide-react";
import { api, eventsSocket, type Trace } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ms, pct } from "@/lib/utils";

type Usage = {
  queries: number; p50_ms: number; p95_ms: number; prompt_tokens: number; completion_tokens: number; not_found_rate: number;
  stage_avg_ms: Record<string, number>; daily: { day: string; queries: number; tokens: number; not_found: number; p50_ms: number; p95_ms: number }[];
  by_mode: Record<string, number>; by_user: Record<string, number>;
};

const tooltipStyle = { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 };

function Kpi({ icon: Icon, label, value, sub }: { icon: React.ElementType; label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="h-3.5 w-3.5" />{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums" data-testid={`kpi-${label}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

export default function UsagePage() {
  const [usage, setUsage] = React.useState<Usage | null>(null);
  const [traces, setTraces] = React.useState<Trace[]>([]);
  const [open, setOpen] = React.useState<number | null>(null);

  const load = React.useCallback(() => {
    api<Usage>("/api/usage").then(setUsage).catch(() => {});
    api<Trace[]>("/api/traces?limit=100").then(setTraces).catch(() => {});
  }, []);
  React.useEffect(() => {
    load();
    return eventsSocket((ev) => {
      if (ev.type === "trace") {
        setTraces((ts) => [ev.trace as Trace, ...ts].slice(0, 100));
        api<Usage>("/api/usage").then(setUsage).catch(() => {});
      }
    });
  }, [load]);

  const stages = usage ? [{ name: "avg per query", retrieval: usage.stage_avg_ms.retrieval_ms, rerank: usage.stage_avg_ms.rerank_ms, llm: usage.stage_avg_ms.llm_ms }] : [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Usage &amp; traces</h1>
        <p className="text-sm text-muted-foreground">Every query is traced: latency per stage, tokens, retrieved chunks and agent steps. Updates live. Admins see all users; members see their own queries.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi icon={Activity} label="Queries" value={String(usage?.queries ?? "–")} sub="last 14 days" />
        <Kpi icon={Timer} label="p50 latency" value={ms(usage?.p50_ms)} sub="end-to-end" />
        <Kpi icon={Gauge} label="p95 latency" value={ms(usage?.p95_ms)} sub="end-to-end" />
        <Kpi icon={Coins} label="Tokens" value={usage ? (usage.prompt_tokens + usage.completion_tokens).toLocaleString() : "–"} sub={usage ? `${usage.completion_tokens.toLocaleString()} generated` : ""} />
        <Kpi icon={CircleSlash} label="Not found" value={pct(usage?.not_found_rate)} sub="answered 'not in documents'" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Queries and latency per day</CardTitle></CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer>
              <ComposedChart data={usage?.daily ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                <YAxis yAxisId="q" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" allowDecimals={false} />
                <YAxis yAxisId="l" orientation="right" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" unit=" ms" />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar yAxisId="q" dataKey="queries" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                <Line yAxisId="l" dataKey="p50_ms" stroke="hsl(var(--warning))" strokeWidth={2} dot />
                <Line yAxisId="l" dataKey="p95_ms" stroke="hsl(var(--destructive))" strokeWidth={2} dot />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Where the time goes</CardTitle>
            <CardDescription>Average ms per stage (LLM generation dominates).</CardDescription>
          </CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer>
              <BarChart data={stages} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" unit=" ms" />
                <YAxis type="category" dataKey="name" hide />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="retrieval" stackId="a" fill="hsl(var(--primary))" />
                <Bar dataKey="rerank" stackId="a" fill="hsl(var(--warning))" />
                <Bar dataKey="llm" stackId="a" fill="hsl(var(--success))" />
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-1 flex flex-wrap gap-1 text-xs">
              {Object.entries(usage?.by_mode ?? {}).map(([k, v]) => <Badge key={k} variant="secondary">{k}: {v}</Badge>)}
              {Object.entries(usage?.by_user ?? {}).map(([k, v]) => <Badge key={k} variant="outline">{k}: {v}</Badge>)}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader><CardTitle>Query traces</CardTitle></CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trace-table">
            <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="w-6 p-2" /><th className="p-2">Time</th><th className="p-2">User</th><th className="p-2">Mode</th><th className="p-2">Question</th>
                <th className="p-2 text-right">Total</th><th className="p-2 text-right">Retrieve</th><th className="p-2 text-right">Rerank</th><th className="p-2 text-right">LLM</th><th className="p-2 text-right">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <React.Fragment key={t.id}>
                  <tr className="cursor-pointer border-t hover:bg-accent/50" onClick={() => setOpen(open === t.id ? null : t.id)}>
                    <td className="p-2">{open === t.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
                    <td className="whitespace-nowrap p-2 text-xs text-muted-foreground">{new Date(t.created_at).toLocaleString()}</td>
                    <td className="p-2">{t.user_id}</td>
                    <td className="p-2"><Badge variant={t.mode === "agent" ? "default" : "secondary"}>{t.mode}</Badge></td>
                    <td className="max-w-md p-2"><div className="truncate">{t.question}</div>{t.not_found && <Badge variant="warning">not found</Badge>}</td>
                    <td className="p-2 text-right tabular-nums">{ms(t.latency_ms)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{ms(t.retrieval_ms)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{ms(t.rerank_ms)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{ms(t.llm_ms)}</td>
                    <td className="p-2 text-right tabular-nums text-muted-foreground">{t.prompt_tokens + t.completion_tokens}</td>
                  </tr>
                  {open === t.id && (
                    <tr className="bg-muted/30">
                      <td />
                      <td colSpan={9} className="space-y-2 p-3 text-xs">
                        <div><span className="font-medium">Answer:</span> {t.answer}</div>
                        {t.steps.length > 0 && (
                          <div>
                            <div className="font-medium">Agent steps</div>
                            {t.steps.map((s, i) => <div key={i} className="text-muted-foreground"><Badge variant="secondary">{s.node}</Badge> {s.detail} ({ms(s.ms)})</div>)}
                          </div>
                        )}
                        <div>
                          <div className="font-medium">Retrieved chunks</div>
                          <table className="mt-1">
                            <tbody>
                              {t.chunks.map((c, i) => (
                                <tr key={c.chunk_id}>
                                  <td className="pr-3">[{i + 1}]</td><td className="pr-3">{c.doc_title} p.{c.page}</td>
                                  <td className="pr-3 text-muted-foreground">rerank {c.rerank_score?.toFixed(3) ?? "–"}</td>
                                  <td className="pr-3 text-muted-foreground">BM25 #{c.bm25_rank ?? "–"}</td>
                                  <td className="text-muted-foreground">vector #{c.vector_rank ?? "–"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {!traces.length && <tr><td colSpan={10} className="p-6 text-center text-muted-foreground">No queries yet - ask something on the Chat page.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
