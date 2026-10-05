"use client";

import { BookOpen, FileText, X } from "lucide-react";

import type { Citation } from "@/lib/types";

interface Props {
  citations: Citation[];
  activeIndex: number | null;
  onSelect: (index: number) => void;
  onClose: () => void;
}

export function CitationsPanel({ citations, activeIndex, onSelect, onClose }: Props) {
  return (
    <aside
      aria-label="Sources"
      className="border-border bg-surface flex h-full w-full flex-col border-l lg:w-96"
    >
      <div className="border-border flex h-12 shrink-0 items-center justify-between border-b px-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <BookOpen className="text-accent size-4" aria-hidden />
          Sources
          {citations.length > 0 && (
            <span className="bg-surface-2 text-muted rounded-full px-2 text-xs">
              {citations.length}
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close sources panel"
          className="text-muted hover:bg-surface-2 hover:text-text rounded-md p-1"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {citations.length === 0 ? (
          <p className="text-muted px-2 py-8 text-center text-sm">
            Click a citation in an answer to see the exact passage it came from.
          </p>
        ) : (
          citations.map((c) => {
            const active = c.index === activeIndex;
            return (
              <button
                key={c.index}
                type="button"
                onClick={() => onSelect(c.index)}
                aria-expanded={active}
                className={`block w-full rounded-xl border p-3 text-left transition-colors ${
                  active
                    ? "border-accent bg-accent-soft/50"
                    : "border-border hover:border-accent/50 hover:bg-surface-2"
                }`}
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="bg-accent text-accent-fg flex size-5 shrink-0 items-center justify-center rounded text-[11px] font-semibold">
                    {c.index}
                  </span>
                  <FileText className="text-muted size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-medium" title={c.filename}>
                    {c.filename}
                  </span>
                </div>
                <div className="text-muted mt-1 flex gap-3 pl-7 text-xs">
                  <span>Page {c.page}</span>
                  <span>Relevance {Math.round(c.score * 100)}%</span>
                </div>
                <blockquote
                  className={`border-accent/40 text-text/90 mt-2 ml-7 border-l-2 pl-3 text-sm leading-relaxed whitespace-pre-wrap ${
                    active ? "" : "line-clamp-3"
                  }`}
                >
                  {c.text}
                </blockquote>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
