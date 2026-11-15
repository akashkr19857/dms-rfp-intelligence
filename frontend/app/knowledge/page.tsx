"use client";

import * as React from "react";
import { CheckCircle2, FileText, Loader2, ScanText, Table2, Trash2, Upload, XCircle } from "lucide-react";
import { api, eventsSocket, type Doc } from "@/lib/api";
import { useAuth } from "@/components/auth";
import { SourceViewer } from "@/components/source-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Progress, Select } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function StatusBadge({ d }: { d: Doc }) {
  if (d.status === "ready") return <Badge variant="success"><CheckCircle2 className="h-3 w-3" /> ready</Badge>;
  if (d.status === "failed") return <Badge variant="destructive" title={d.error}><XCircle className="h-3 w-3" /> failed</Badge>;
  return <Badge variant="warning"><Loader2 className="h-3 w-3 animate-spin" /> {d.status}</Badge>;
}

export default function KnowledgePage() {
  const { user } = useAuth();
  const [docs, setDocs] = React.useState<Doc[]>([]);
  const [selected, setSelected] = React.useState<Doc | null>(null);
  const [workspace, setWorkspace] = React.useState(user?.workspaces.includes("knowledge-base") ? "knowledge-base" : user?.workspaces[0] ?? "");
  const [file, setFile] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [uploading, setUploading] = React.useState(false);
  const [error, setError] = React.useState("");
  const fileRef = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(() => api<Doc[]>("/api/documents").then(setDocs).catch((e) => setError(e.message)), []);
  React.useEffect(() => {
    load();
    return eventsSocket((ev) => {
      if (ev.type === "document") {
        const d = ev.document as Doc;
        setDocs((ds) => (ds.some((x) => x.id === d.id) ? ds.map((x) => (x.id === d.id ? d : x)) : [...ds, d]));
      } else if (ev.type === "document_deleted") setDocs((ds) => ds.filter((x) => x.id !== ev.id));
    });
  }, [load]);

  const upload = async () => {
    if (!file || !workspace) return;
    setUploading(true);
    setError("");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("workspace", workspace);
    fd.append("title", title);
    try {
      const d = await api<Doc>("/api/documents", { method: "POST", body: fd });
      setDocs((ds) => (ds.some((x) => x.id === d.id) ? ds : [...ds, d]));
      setFile(null);
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const remove = async (d: Doc) => {
    if (!confirm(`Delete "${d.title}" and its index entries?`)) return;
    await api(`/api/documents/${d.id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    setDocs((ds) => ds.filter((x) => x.id !== d.id));
    if (selected?.id === d.id) setSelected(null);
  };

  const totals = docs.reduce((a, d) => ({ pages: a.pages + d.pages, chunks: a.chunks + d.n_chunks, ocr: a.ocr + d.ocr_pages, tables: a.tables + d.tables }), { pages: 0, chunks: 0, ocr: 0, tables: 0 });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Knowledge base &amp; document library</h1>
          <p className="text-sm text-muted-foreground">
            {docs.length} documents · {totals.pages} pages · {totals.chunks} chunks · {totals.tables} tables · {totals.ocr} OCR pages
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add to the knowledge base</CardTitle>
          <CardDescription>Company profiles, policies, past proposals, case studies, CVs (PDF or DOCX). Text, tables and scanned pages (OCR) are extracted, chunked with page/section metadata, embedded and indexed; the compliance checker and proposal writer use them immediately.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept=".pdf,.docx" data-testid="upload-input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm file:mr-2 file:rounded-md file:border file:bg-card file:px-3 file:py-1.5 file:text-sm" />
          <Input className="w-56" placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
          <Select value={workspace} onChange={(e) => setWorkspace(e.target.value)} aria-label="Target workspace">
            {(user?.workspaces ?? []).map((w) => <option key={w} value={w}>{w}</option>)}
          </Select>
          <Button onClick={upload} disabled={!file || uploading} data-testid="upload-button">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload &amp; index
          </Button>
          {error && <span className="text-sm text-destructive">{error}</span>}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="doc-table">
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="p-3">Document</th>
                  <th className="p-3">Workspace</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Pages</th>
                  <th className="p-3 text-right">Chunks</th>
                  <th className="p-3">Content</th>
                  <th className="p-3 text-right">Ingest</th>
                  <th className="p-3" />
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} onClick={() => d.status === "ready" && setSelected(d)} className={cn("cursor-pointer border-t hover:bg-accent/50", selected?.id === d.id && "bg-primary/5")}>
                    <td className="p-3">
                      <div className="flex items-center gap-2 font-medium"><FileText className="h-4 w-4 shrink-0 text-primary" />{d.title}</div>
                      <div className="ml-6 text-xs text-muted-foreground">{d.filename}</div>
                      {d.status === "processing" && <Progress value={d.progress} className="ml-6 mt-1 w-40" />}
                    </td>
                    <td className="p-3"><Badge variant="secondary">{d.workspace_id}</Badge></td>
                    <td className="p-3"><StatusBadge d={d} /></td>
                    <td className="p-3 text-right tabular-nums">{d.pages || "–"}</td>
                    <td className="p-3 text-right tabular-nums">{d.n_chunks || "–"}</td>
                    <td className="p-3">
                      <div className="flex gap-1">
                        {d.tables > 0 && <Badge variant="outline"><Table2 className="h-3 w-3" />{d.tables} tables</Badge>}
                        {d.ocr_pages > 0 && <Badge variant="warning"><ScanText className="h-3 w-3" />{d.ocr_pages} OCR</Badge>}
                      </div>
                    </td>
                    <td className="p-3 text-right tabular-nums text-muted-foreground">{d.ingest_seconds ? `${d.ingest_seconds.toFixed(0)} s` : "–"}</td>
                    <td className="p-3 text-right">
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); remove(d); }} aria-label={`Delete ${d.title}`}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
                {!docs.length && (
                  <tr><td colSpan={8} className="p-6 text-center text-muted-foreground">No documents in your workspaces yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
        <Card className="flex h-[640px] flex-col">
          <CardHeader className="pb-1"><CardTitle>Preview</CardTitle></CardHeader>
          <CardContent className="min-h-0 flex-1">
            {selected ? (
              <SourceViewer source={{ docId: selected.id, page: 1, pages: selected.pages, title: selected.title, fileType: selected.file_type, text: "Word document: open it from the Ask page or a citation to see cited passages." }} />
            ) : (
              <p className="text-sm text-muted-foreground">Select a ready document to page through it.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
