"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, CalendarClock, CheckCircle2, FileText, Loader2, Play, Upload } from "lucide-react";
import { api, eventsSocket, type Analysis, type Doc, type TenderSummary } from "@/lib/api";
import { useAuth } from "@/components/auth";
import { AnalysisProgress, ScoreGauge, StatusBar } from "@/components/tender-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/input";

export default function TendersPage() {
  const { user } = useAuth();
  const [tenders, setTenders] = React.useState<TenderSummary[]>([]);
  const [loaded, setLoaded] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [error, setError] = React.useState("");
  const fileRef = React.useRef<HTMLInputElement>(null);
  const canSee = user?.workspaces.includes("tenders");

  const load = React.useCallback(
    () => api<TenderSummary[]>("/api/tenders").then(setTenders).catch((e) => setError(e.message)).finally(() => setLoaded(true)),
    [],
  );
  React.useEffect(() => {
    if (!canSee) return;
    load();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(load, 800); // counts change with analysis; refetch shortly after the burst of events
    };
    const stop = eventsSocket((ev) => {
      if (ev.type === "analysis") {
        const a = ev.analysis as Analysis;
        setTenders((ts) => ts.map((t) => (t.document.id === a.doc_id ? { ...t, analysis: a } : t)));
        if (a.status === "done" || a.status === "failed") refresh();
      } else if (ev.type === "document") {
        const d = ev.document as Doc;
        if (d.workspace_id !== "tenders") return;
        setTenders((ts) => (ts.some((t) => t.document.id === d.id) ? ts.map((t) => (t.document.id === d.id ? { ...t, document: d } : t))
          : [...ts, { document: d, analysis: null, requirements: 0, status_counts: {}, risks: 0, high_risks: 0 }]));
      }
    });
    return () => {
      stop();
      clearTimeout(timer);
    };
  }, [load, canSee]);

  const upload = async () => {
    if (!file) return;
    setUploading(true);
    setError("");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("workspace", "tenders");
    fd.append("analyze", "true");
    try {
      await api<Doc>("/api/documents", { method: "POST", body: fd });
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const analyze = async (id: number) => {
    setError("");
    await api(`/api/tenders/${id}/analyze`, { method: "POST" }).catch((e) => setError(e.message));
  };

  if (!canSee) return <p className="text-sm text-muted-foreground">Your role has no access to tenders.</p>;
  const done = tenders.filter((t) => t.analysis?.status === "done");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Tender pipeline</h1>
          <p className="text-sm text-muted-foreground">
            {tenders.length} RFPs · {done.length} analysed · {done.reduce((s, t) => s + t.requirements, 0)} requirements extracted ·{" "}
            {done.reduce((s, t) => s + t.high_risks, 0)} high risks flagged
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Upload an RFP / tender</CardTitle>
          <CardDescription>PDF or DOCX. It is parsed, indexed and then analysed automatically: key facts, requirements, compliance against your knowledge base, risks and a bid score.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept=".pdf,.docx" data-testid="rfp-upload-input" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm file:mr-2 file:rounded-md file:border file:bg-card file:px-3 file:py-1.5 file:text-sm" />
          <Button onClick={upload} disabled={!file || uploading} data-testid="rfp-upload-button">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload &amp; analyse
          </Button>
          {error && <span className="text-sm text-destructive">{error}</span>}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3" data-testid="tender-list">
        {tenders.map((t) => {
          const a = t.analysis;
          const d = t.document;
          const deadline = a?.facts?.submission_deadline?.value;
          const issuer = a?.facts?.issuer?.value;
          const running = a && (a.status === "running" || a.status === "queued");
          const hasScore = a?.status === "done" && a.bid_score && "score" in a.bid_score;
          return (
            <Card key={d.id} className="flex flex-col" data-testid={`tender-${d.id}`}>
              <CardHeader className="flex-row items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <Link href={`/tenders/${d.id}`} className="line-clamp-2 font-semibold hover:text-primary">{d.title}</Link>
                  <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
                    <Badge variant="secondary"><FileText className="h-3 w-3" />{d.file_type.toUpperCase()} · {d.pages} pages</Badge>
                    {issuer && <span className="truncate">{issuer}</span>}
                  </div>
                </div>
                {hasScore && <ScoreGauge score={a!.bid_score as never} size={110} />}
              </CardHeader>
              <CardContent className="mt-auto space-y-3">
                {d.status !== "ready" ? (
                  <div className="space-y-1 text-xs text-muted-foreground"><span>Indexing document… {Math.round(d.progress * 100)}%</span><Progress value={d.progress} /></div>
                ) : running ? (
                  <AnalysisProgress a={a!} />
                ) : a?.status === "done" ? (
                  <>
                    {deadline && <div className="flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-primary" /><span className="font-medium">Due:</span> {deadline}</div>}
                    <StatusBar counts={t.status_counts} />
                    <div className="flex flex-wrap gap-2 text-xs">
                      <Badge variant="outline"><CheckCircle2 className="h-3 w-3" />{t.requirements} requirements</Badge>
                      <Badge variant={t.high_risks ? "destructive" : "outline"}><AlertTriangle className="h-3 w-3" />{t.risks} risks · {t.high_risks} high</Badge>
                    </div>
                    <Button asChild variant="outline" size="sm" className="w-full"><Link href={`/tenders/${d.id}`}>Open analysis</Link></Button>
                  </>
                ) : (
                  <div className="space-y-2">
                    {a?.status === "failed" && <p className="text-xs text-destructive">{a.error}</p>}
                    <Button size="sm" className="w-full" onClick={() => analyze(d.id)} data-testid={`analyze-${d.id}`}><Play className="h-4 w-4" /> Analyse RFP</Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
        {loaded && !tenders.length && <p className="text-sm text-muted-foreground">No tenders yet. Upload an RFP to start.</p>}
      </div>
    </div>
  );
}
