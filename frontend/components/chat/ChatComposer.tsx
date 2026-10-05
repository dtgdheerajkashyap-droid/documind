"use client";

import { Check, Filter, SendHorizontal, Square } from "lucide-react";
import { useState } from "react";

import type { DocumentItem } from "@/lib/types";

interface Props {
  onSend: (question: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  documents: DocumentItem[];
  selectedDocIds: string[];
  onSelectedDocIdsChange: (ids: string[]) => void;
}

function DocumentFilter({
  documents,
  selected,
  onChange,
}: {
  documents: DocumentItem[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const label =
    selected.length === 0
      ? "All documents"
      : `${selected.length} document${selected.length > 1 ? "s" : ""}`;

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition-colors ${
          selected.length ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2"
        }`}
      >
        <Filter className="size-3.5" aria-hidden />
        {label}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden />
          <div
            role="listbox"
            aria-multiselectable
            aria-label="Search in documents"
            className="border-border bg-surface absolute bottom-full left-0 z-20 mb-2 max-h-72 w-72 overflow-y-auto rounded-xl border p-1 shadow-lg"
          >
            <button
              type="button"
              role="option"
              aria-selected={selected.length === 0}
              onClick={() => onChange([])}
              className="hover:bg-surface-2 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm"
            >
              <Check
                className={`size-4 ${selected.length === 0 ? "text-accent" : "invisible"}`}
                aria-hidden
              />
              All documents
            </button>
            {documents.length === 0 && (
              <p className="text-muted px-2 py-1.5 text-sm">No ready documents.</p>
            )}
            {documents.map((doc) => (
              <button
                key={doc.id}
                type="button"
                role="option"
                aria-selected={selected.includes(doc.id)}
                onClick={() => toggle(doc.id)}
                className="hover:bg-surface-2 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm"
              >
                <Check
                  className={`size-4 shrink-0 ${selected.includes(doc.id) ? "text-accent" : "invisible"}`}
                  aria-hidden
                />
                <span className="truncate">{doc.filename}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function ChatComposer({
  onSend,
  onStop,
  isStreaming,
  documents,
  selectedDocIds,
  onSelectedDocIdsChange,
}: Props) {
  const [value, setValue] = useState("");

  function submit() {
    const question = value.trim();
    if (!question || isStreaming) return;
    onSend(question);
    setValue("");
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="border-border bg-surface focus-within:border-accent rounded-2xl border p-2 shadow-sm transition-colors"
    >
      <label htmlFor="question" className="sr-only">
        Ask a question about your documents
      </label>
      <textarea
        id="question"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        rows={2}
        maxLength={2000}
        placeholder="Ask a question about your documents…"
        className="placeholder:text-muted w-full resize-none bg-transparent px-2 py-1 outline-none"
      />
      <div className="flex items-center justify-between gap-2">
        <DocumentFilter
          documents={documents}
          selected={selectedDocIds}
          onChange={onSelectedDocIdsChange}
        />
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            className="bg-surface-2 hover:bg-border flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium"
          >
            <Square className="size-3.5 fill-current" aria-hidden />
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            aria-label="Send"
            className="bg-accent text-accent-fg hover:bg-accent-hover flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
            <SendHorizontal className="size-4" aria-hidden />
          </button>
        )}
      </div>
    </form>
  );
}
