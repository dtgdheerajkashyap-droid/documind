"use client";

import { AlertCircle, BrainCircuit, FileSearch, User } from "lucide-react";
import { Fragment } from "react";

import type { Citation, UiMessage } from "@/lib/types";

interface Props {
  message: UiMessage;
  activeCitation?: number | null;
  onCitationClick?: (index: number) => void;
}

const MARKER = /(\[\d{1,2}\])/g;

/** Render answer text, turning [n] markers that match a citation into buttons. */
function AnswerText({
  content,
  citations,
  activeCitation,
  onCitationClick,
}: {
  content: string;
  citations: Citation[];
  activeCitation?: number | null;
  onCitationClick?: (index: number) => void;
}) {
  const known = new Set(citations.map((c) => c.index));
  return (
    <>
      {content.split(MARKER).map((part, i) => {
        const match = /^\[(\d{1,2})\]$/.exec(part);
        const index = match ? Number(match[1]) : null;
        if (index === null || !known.has(index)) return <Fragment key={i}>{part}</Fragment>;
        return (
          <button
            key={i}
            type="button"
            onClick={() => onCitationClick?.(index)}
            aria-label={`Show source ${index}`}
            className={`mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded px-1 align-middle text-[11px] font-semibold transition-colors ${
              activeCitation === index
                ? "bg-accent text-accent-fg"
                : "bg-accent-soft text-accent hover:bg-accent hover:text-accent-fg"
            }`}
          >
            {index}
          </button>
        );
      })}
    </>
  );
}

export function ChatMessage({ message, activeCitation, onCitationClick }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-3">
        <div className="bg-accent text-accent-fg max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 whitespace-pre-wrap sm:max-w-[75%]">
          {message.content}
        </div>
        <span className="bg-surface-2 text-muted hidden size-8 shrink-0 items-center justify-center rounded-full sm:flex">
          <User className="size-4" aria-hidden />
        </span>
      </div>
    );
  }

  const streaming = message.status === "streaming";
  const waiting = streaming && message.content.length === 0;

  return (
    <div className="flex gap-3" data-testid="assistant-message">
      <span className="bg-accent-soft text-accent flex size-8 shrink-0 items-center justify-center rounded-full">
        <BrainCircuit className="size-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div
          className={`border-border bg-surface rounded-2xl rounded-tl-md border px-4 py-3 leading-relaxed whitespace-pre-wrap ${
            message.refused ? "text-muted italic" : ""
          }`}
        >
          {waiting ? (
            <span className="text-muted inline-flex items-center gap-2 text-sm not-italic">
              <FileSearch className="size-4 animate-pulse" aria-hidden />
              Searching your documents…
            </span>
          ) : (
            <span className={streaming ? "streaming-caret" : undefined}>
              <AnswerText
                content={message.content}
                citations={message.citations}
                activeCitation={activeCitation}
                onCitationClick={onCitationClick}
              />
            </span>
          )}
        </div>

        {message.status === "error" && (
          <p role="alert" className="text-danger mt-2 flex items-start gap-1.5 text-sm">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {message.error}
          </p>
        )}

        {message.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sources">
            {message.citations.map((c) => (
              <button
                key={c.index}
                type="button"
                onClick={() => onCitationClick?.(c.index)}
                className={`border-border hover:border-accent hover:text-accent max-w-full truncate rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                  activeCitation === c.index ? "border-accent text-accent" : "text-muted"
                }`}
                title={`${c.filename}, page ${c.page}`}
              >
                [{c.index}] {c.filename} · p. {c.page}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
