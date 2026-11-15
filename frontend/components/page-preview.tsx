"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, ExternalLink, Loader2 } from "lucide-react";
import { API_URL, getToken, pageImageUrl } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** Renders a PDF page (server-side via PyMuPDF) with the cited chunk highlighted. */
export function PagePreview({ docId, page, chunkId, pages, title }: { docId: number; page: number; chunkId?: string; pages?: number; title?: string }) {
  const [current, setCurrent] = React.useState(page);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    setCurrent(page);
  }, [page, docId, chunkId]);
  React.useEffect(() => {
    setLoading(true);
  }, [current, docId, chunkId]);
  const highlight = current === page ? chunkId : undefined;
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <div className="min-w-0 truncate font-medium" title={title}>
          {title} · page {current}
          {pages ? ` / ${pages}` : ""}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={current <= 1} onClick={() => setCurrent((c) => c - 1)} aria-label="Previous page">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={!!pages && current >= pages} onClick={() => setCurrent((c) => c + 1)} aria-label="Next page">
            <ChevronRight className="h-4 w-4" />
          </Button>
          <a
            className="inline-flex h-7 items-center gap-1 rounded px-2 text-muted-foreground hover:bg-accent"
            href={`${API_URL}/api/documents/${docId}/file?token=${encodeURIComponent(getToken() ?? "")}#page=${current}`}
            target="_blank"
            rel="noreferrer"
          >
            PDF <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
      <div className="relative min-h-[300px] flex-1 overflow-auto rounded-md border bg-white">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          data-testid="page-image"
          src={pageImageUrl(docId, current, highlight)}
          alt={`${title ?? "document"} page ${current}`}
          className="w-full"
          onLoad={() => setLoading(false)}
          onError={() => setLoading(false)}
        />
      </div>
    </div>
  );
}
