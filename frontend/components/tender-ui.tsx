"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, CircleHelp, ClipboardList, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { Analysis, BidScore } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const STATUS_META: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "secondary" | "default" | "outline"; icon: React.ElementType; color: string }> = {
  met: { label: "Met", variant: "success", icon: CheckCircle2, color: "hsl(var(--success))" },
  partial: { label: "Partial", variant: "warning", icon: MinusCircle, color: "hsl(var(--warning))" },
  gap: { label: "Gap", variant: "destructive", icon: XCircle, color: "hsl(var(--destructive))" },
  unknown: { label: "Unknown", variant: "secondary", icon: CircleHelp, color: "hsl(var(--muted-foreground))" },
  action: { label: "Checklist", variant: "default", icon: ClipboardList, color: "hsl(var(--primary))" },
  pending: { label: "Pending", variant: "outline", icon: CircleDashed, color: "hsl(var(--border))" },
};

export function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  const Icon = m.icon;
  return <Badge variant={m.variant} data-testid={`status-${status}`}><Icon className="h-3 w-3" />{m.label}</Badge>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const v = severity === "high" ? "destructive" : severity === "medium" ? "warning" : "secondary";
  return <Badge variant={v}><AlertTriangle className="h-3 w-3" />{severity}</Badge>;
}

const STAGE_LABEL: Record<string, string> = {
  queued: "Queued", facts: "Extracting key facts", criteria: "Reading evaluation criteria", requirements: "Extracting requirements",
  compliance: "Checking compliance against knowledge base", risks: "Detecting risks & gaps", score: "Scoring", done: "Done",
};

export function AnalysisProgress({ a }: { a: Analysis }) {
  if (a.status === "failed") return <p className="text-sm text-destructive">Analysis failed: {a.error}</p>;
  return (
    <div className="space-y-1" data-testid="analysis-progress">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        {STAGE_LABEL[a.stage] ?? a.stage} · {Math.round(a.progress * 100)}% · {a.llm_calls} LLM calls
      </div>
      <Progress value={a.progress} />
    </div>
  );
}

export function recColor(rec: string) {
  return rec === "Bid" ? "text-success" : rec === "No bid" ? "text-destructive" : "text-warning";
}

/** Semicircle gauge for the 0-100 bid score. */
export function ScoreGauge({ score, size = 132 }: { score: BidScore; size?: number }) {
  const r = 52;
  const c = Math.PI * r;
  const v = Math.max(0, Math.min(100, score.score));
  const color = score.recommendation === "Bid" ? "hsl(var(--success))" : score.recommendation === "No bid" ? "hsl(var(--destructive))" : "hsl(var(--warning))";
  return (
    <div className="flex flex-col items-center" data-testid="bid-score">
      <svg width={size} height={size * 0.62} viewBox="0 0 124 76" role="img" aria-label={`Bid score ${v} of 100`}>
        <path d="M 10 66 A 52 52 0 0 1 114 66" fill="none" stroke="hsl(var(--muted))" strokeWidth="11" strokeLinecap="round" />
        <path d="M 10 66 A 52 52 0 0 1 114 66" fill="none" stroke={color} strokeWidth="11" strokeLinecap="round" strokeDasharray={`${(c * v) / 100} ${c}`} />
        <text x="62" y="60" textAnchor="middle" fontSize="24" fontWeight="700" fill="hsl(var(--foreground))">{Math.round(v)}</text>
      </svg>
      <div className={cn("text-sm font-semibold", recColor(score.recommendation))}>{score.recommendation}</div>
    </div>
  );
}

export function StatusBar({ counts }: { counts: Record<string, number> }) {
  const order = ["met", "partial", "gap", "unknown", "action"];
  const total = order.reduce((s, k) => s + (counts[k] ?? 0), 0);
  if (!total) return null;
  return (
    <div className="space-y-1">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
        {order.map((k) => (counts[k] ? <div key={k} style={{ width: `${(100 * counts[k]) / total}%`, background: STATUS_META[k].color }} title={`${STATUS_META[k].label}: ${counts[k]}`} /> : null))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
        {order.map((k) => (counts[k] ? (
          <span key={k} className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_META[k].color }} />{STATUS_META[k].label} {counts[k]}</span>
        ) : null))}
      </div>
    </div>
  );
}
