"use client";

import * as React from "react";
import { FileText, X } from "lucide-react";
import { PagePreview } from "@/components/page-preview";
import { Button } from "@/components/ui/button";

export type SourceRef = { docId: number; page: number; chunkId?: string; title: string; fileType?: "pdf" | "docx"; text?: string; pages?: number };

/** Shows a cited source: the highlighted PDF page, or the cited passage for Word documents (no fixed pages). */
export function SourceViewer({ source, onClose }: { source: SourceRef | null; onClose?: () => void }) {
  if (!source) {
    return <p className="p-2 text-sm text-muted-foreground">Click any page reference or citation to see the exact source here.</p>;
  }
  return (
    <div className="flex h-full min-h-0 flex-col gap-2" data-testid="source-viewer">
      {onClose && (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close source"><X className="h-4 w-4" /> Close</Button>
        </div>
      )}
      {source.fileType === "docx" ? (
        <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
          <div className="flex items-center gap-2 font-medium"><FileText className="h-4 w-4 text-primary" />{source.title} · part {source.page}</div>
          <p className="whitespace-pre-wrap leading-relaxed">{source.text || "(cited passage)"}</p>
          <p className="text-xs text-muted-foreground">Word document: citations point to the document part (section), not a printed page.</p>
        </div>
      ) : (
        <PagePreview docId={source.docId} page={source.page} chunkId={source.chunkId} pages={source.pages} title={source.title} />
      )}
    </div>
  );
}
