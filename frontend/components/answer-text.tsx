"use client";

import * as React from "react";
import type { Citation } from "@/lib/api";

/** Minimal markdown (paragraphs, bullet/numbered lists, **bold**, tables) with clickable [n] citation chips. */
export function AnswerText({ text, citations, onCite }: { text: string; citations: Citation[]; onCite: (n: number) => void }) {
  const valid = new Set(citations.map((c) => c.n));

  const inline = (s: string, key: string) => {
    const parts = s.split(/(\*\*[^*]+\*\*|\[\d{1,2}\])/g);
    return parts.map((p, i) => {
      const cite = p.match(/^\[(\d{1,2})\]$/);
      if (cite) {
        const n = Number(cite[1]);
        if (!valid.has(n)) return <sup key={`${key}-${i}`} className="text-muted-foreground">[{n}]</sup>;
        return (
          <button
            key={`${key}-${i}`}
            data-testid="citation"
            onClick={() => onCite(n)}
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-primary/15 px-1 align-text-top text-[11px] font-semibold text-primary hover:bg-primary hover:text-primary-foreground"
            title="Show source page"
          >
            {n}
          </button>
        );
      }
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={`${key}-${i}`}>{p.slice(2, -2)}</strong>;
      return <React.Fragment key={`${key}-${i}`}>{p}</React.Fragment>;
    });
  };

  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) {
      i++;
      continue;
    }
    if (/^\|.*\|$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\|.*\|$/.test(lines[i].trim())) {
        const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push(
        <table key={`t${i}`}>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri} className={ri === 0 ? "bg-muted font-medium" : ""}>
                {r.map((c, ci) => <td key={ci}>{inline(c, `t${i}-${ri}-${ci}`)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (/^([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^([-*•]|\d+[.)])\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(<Tag key={`l${i}`}>{items.map((it, k) => <li key={k}>{inline(it, `l${i}-${k}`)}</li>)}</Tag>);
      continue;
    }
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    blocks.push(heading ? <p key={`p${i}`} className="font-semibold">{inline(heading[1], `h${i}`)}</p> : <p key={`p${i}`}>{inline(line, `p${i}`)}</p>);
    i++;
  }
  return <div className="prose-answer text-sm">{blocks}</div>;
}
