"use client";

import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { Spinner } from "@/components/ui/Feedback";
import { formatRelativeTime } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

interface Props {
  sessions: SessionSummary[];
  loading: boolean;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function SessionSidebar({ sessions, loading, activeId, onSelect, onNew, onDelete }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="border-border bg-surface hover:border-accent hover:text-accent flex w-full items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-colors"
        >
          <Plus className="size-4" aria-hidden />
          New chat
        </button>
      </div>
      <p className="text-muted px-4 pb-1 text-xs font-medium tracking-wide uppercase">History</p>
      <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Chat history">
        {loading ? (
          <div className="p-3">
            <Spinner label="Loading chats" />
          </div>
        ) : sessions.length === 0 ? (
          <p className="text-muted px-2 py-3 text-sm">No conversations yet.</p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => (
              <li key={s.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  aria-current={s.id === activeId ? "true" : undefined}
                  className={`flex w-full items-start gap-2 rounded-lg px-2 py-2 pr-8 text-left text-sm transition-colors ${
                    s.id === activeId ? "bg-accent-soft text-accent" : "hover:bg-surface-2"
                  }`}
                >
                  <MessageSquare className="mt-0.5 size-4 shrink-0 opacity-60" aria-hidden />
                  <span className="min-w-0">
                    <span className="block truncate">{s.title}</span>
                    <span className="text-muted block text-xs">
                      {formatRelativeTime(s.updated_at)}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(s.id)}
                  aria-label={`Delete chat ${s.title}`}
                  className="text-muted hover:text-danger absolute top-2 right-1.5 rounded p-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>
    </div>
  );
}
