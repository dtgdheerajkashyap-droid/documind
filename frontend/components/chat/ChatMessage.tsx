"use client";

import {
  AlertCircle,
  BrainCircuit,
  Check,
  Copy,
  FileSearch,
  FileText,
  SearchX,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Markdown } from "@/components/chat/Markdown";
import { toPlainText } from "@/lib/markdown";
import type { Citation, UiMessage } from "@/lib/types";

interface Props {
  message: UiMessage;
  activeCitation?: number | null;
  onCitationClick?: (index: number) => void;
}

export function ChatMessage({ message, activeCitation, onCitationClick }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-accent text-accent-fg max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap shadow-sm sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <AssistantMessage
      message={message}
      activeCitation={activeCitation}
      onCitationClick={onCitationClick}
    />
  );
}

function AssistantMessage({ message, activeCitation, onCitationClick }: Props) {
  const streaming = message.status === "streaming";
  const waiting = streaming && message.content.length === 0;
  const known = useMemo(() => new Set(message.citations.map((c) => c.index)), [message.citations]);

  return (
    <article className="flex gap-3" data-testid="assistant-message">
      <span className="from-accent flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br to-fuchsia-500 text-white shadow-sm">
        <BrainCircuit className="size-4" aria-hidden />
      </span>

      <div className="min-w-0 flex-1">
        <header className="mb-2 flex h-8 items-center gap-2">
          <span className="text-sm font-semibold">DocuMind</span>
          <StatusChip message={message} />
        </header>

        {message.refused ? (
          <div className="border-warning/30 bg-warning-soft flex gap-3 rounded-2xl border px-4 py-3.5">
            <SearchX className="text-warning mt-0.5 size-5 shrink-0" aria-hidden />
            <div className="space-y-1">
              <p className="text-[15px] font-medium">{message.content}</p>
              <p className="text-muted text-sm">
                Try rephrasing, naming the section (for example &ldquo;Program 4&rdquo;), or
                checking which documents are selected.
              </p>
            </div>
          </div>
        ) : (
          <div className="border-border bg-surface rounded-2xl rounded-tl-md border px-5 py-4 shadow-sm">
            {waiting ? (
              <span className="text-muted inline-flex items-center gap-2 text-sm">
                <FileSearch className="size-4 animate-pulse" aria-hidden />
                Searching your documents…
              </span>
            ) : (
              <Markdown
                content={message.content}
                citations={known}
                activeCitation={activeCitation}
                onCitationClick={onCitationClick}
                streaming={streaming}
              />
            )}
          </div>
        )}

        {message.status === "error" && (
          <p role="alert" className="text-danger mt-2 flex items-start gap-1.5 text-sm">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {message.error}
          </p>
        )}

        {message.citations.length > 0 && (
          <Sources
            citations={message.citations}
            activeCitation={activeCitation}
            onCitationClick={onCitationClick}
          />
        )}

        {message.status === "done" && !message.refused && message.content && (
          <div className="mt-2 flex">
            <CopyButton text={toPlainText(message.content)} />
          </div>
        )}
      </div>
    </article>
  );
}

function StatusChip({ message }: { message: UiMessage }) {
  const chip = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium";
  if (message.status === "streaming") {
    return (
      <span className={`${chip} bg-surface-2 text-muted`}>
        <span className="bg-accent size-1.5 animate-pulse rounded-full" aria-hidden />
        {message.content ? "Writing" : "Searching"}
      </span>
    );
  }
  if (message.status === "done" && !message.refused && message.citations.length > 0) {
    const n = message.citations.length;
    return (
      <span className={`${chip} bg-success-soft text-success`}>
        <ShieldCheck className="size-3.5" aria-hidden />
        Grounded in {n} source{n > 1 ? "s" : ""}
      </span>
    );
  }
  return null;
}

function Sources({
  citations,
  activeCitation,
  onCitationClick,
}: {
  citations: Citation[];
  activeCitation?: number | null;
  onCitationClick?: (index: number) => void;
}) {
  return (
    <section className="mt-3" aria-label="Sources">
      <h3 className="text-muted mb-1.5 text-xs font-semibold tracking-wide uppercase">Sources</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        {citations.map((c) => {
          const active = activeCitation === c.index;
          return (
            <button
              key={c.index}
              type="button"
              onClick={() => onCitationClick?.(c.index)}
              aria-label={`Source ${c.index}: ${c.filename}, page ${c.page}`}
              className={`group flex min-w-0 items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                active
                  ? "border-accent bg-accent-soft/60"
                  : "border-border bg-surface hover:border-accent/50 hover:bg-surface-2"
              }`}
            >
              <span
                className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md text-[11px] font-semibold ${
                  active ? "bg-accent text-accent-fg" : "bg-accent-soft text-accent"
                }`}
              >
                {c.index}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <FileText className="text-muted size-3.5 shrink-0" aria-hidden />
                  <span className="truncate">{c.filename}</span>
                  <span className="text-muted shrink-0 text-xs font-normal">p. {c.page}</span>
                </span>
                <span className="text-muted mt-0.5 line-clamp-2 text-xs leading-relaxed">
                  {c.text}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => setCopied(true))
          .catch(() => undefined);
      }}
      className="text-muted hover:bg-surface-2 hover:text-text inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors"
    >
      {copied ? (
        <Check className="size-3.5" aria-hidden />
      ) : (
        <Copy className="size-3.5" aria-hidden />
      )}
      {copied ? "Copied" : "Copy answer"}
    </button>
  );
}
