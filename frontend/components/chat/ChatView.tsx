"use client";

import { BookOpen, BrainCircuit, PanelLeft, Upload, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { CitationsPanel } from "@/components/chat/CitationsPanel";
import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { EmptyState, ErrorBanner, Spinner } from "@/components/ui/Feedback";
import { useChat } from "@/hooks/useChat";
import { useDocuments } from "@/hooks/useDocuments";
import { ApiError, api } from "@/lib/api";
import type { Health } from "@/lib/types";

const SUGGESTIONS = [
  "Summarize the main points of my documents.",
  "What are the key dates or deadlines mentioned?",
  "List any policies or rules described.",
];

export function ChatView() {
  const chat = useChat();
  const { documents, loading: docsLoading } = useDocuments();
  const readyDocs = useMemo(() => documents.filter((d) => d.status === "ready"), [documents]);

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [selection, setSelection] = useState<{ messageId: string; index: number } | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((err) =>
        setHealthError(err instanceof ApiError ? err.message : "Cannot reach the API."),
      );
  }, []);

  // Keep the newest content in view while answers stream in.
  const lastMessage = chat.messages.at(-1);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.messages.length, lastMessage?.content]);

  // Citations shown in the panel: the selected message, else the latest answer with sources.
  const panelMessage = useMemo(() => {
    const byId = selection && chat.messages.find((m) => m.id === selection.messageId);
    if (byId) return byId;
    return [...chat.messages].reverse().find((m) => m.citations.length > 0) ?? null;
  }, [chat.messages, selection]);
  const panelCitations = panelMessage?.citations ?? [];
  const activeIndex =
    selection && panelMessage?.id === selection.messageId ? selection.index : null;

  const openCitation = (messageId: string, index: number) => {
    setSelection({ messageId, index });
    setPanelOpen(true);
  };

  const send = (question: string) => {
    setSelection(null);
    void chat.send(question, selectedDocIds);
  };

  const sidebar = (
    <SessionSidebar
      sessions={chat.sessions}
      loading={chat.sessionsLoading}
      activeId={chat.activeSessionId}
      onSelect={(id) => {
        setSelection(null);
        setSidebarOpen(false);
        void chat.selectSession(id);
      }}
      onNew={() => {
        setSelection(null);
        setSidebarOpen(false);
        chat.newChat();
      }}
      onDelete={(id) => void chat.deleteSession(id)}
    />
  );

  return (
    <div className="flex min-h-0 flex-1">
      {/* Session history: fixed column on desktop, drawer on mobile */}
      <div className="border-border bg-surface hidden w-64 shrink-0 border-r md:block">
        {sidebar}
      </div>
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setSidebarOpen(false)} />
          <div className="bg-surface absolute inset-y-0 left-0 w-72 shadow-xl">
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close chat history"
              className="text-muted absolute top-3 right-3 p-1"
            >
              <X className="size-4" />
            </button>
            <div className="h-full pt-8">{sidebar}</div>
          </div>
        </div>
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="border-border flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open chat history"
            className="text-muted hover:bg-surface-2 rounded-md p-1.5 md:hidden"
          >
            <PanelLeft className="size-4" />
          </button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">
            {chat.sessions.find((s) => s.id === chat.activeSessionId)?.title ?? "New chat"}
          </h1>
          <button
            type="button"
            onClick={() => setPanelOpen((o) => !o)}
            aria-pressed={panelOpen}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm transition-colors ${
              panelOpen ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2"
            }`}
          >
            <BookOpen className="size-4" aria-hidden />
            <span className="hidden sm:inline">Sources</span>
            {panelCitations.length > 0 && (
              <span className="text-xs">({panelCitations.length})</span>
            )}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl space-y-3 px-4 pt-4">
            {healthError && <ErrorBanner message={healthError} />}
            {health && !health.llm_configured && (
              <ErrorBanner
                tone="warning"
                message={`The language model (${health.llm_provider}) is not configured. Set GEMINI_API_KEY in your .env file and restart the backend.`}
              />
            )}
            {chat.error && (
              <ErrorBanner message={chat.error} onDismiss={() => chat.setError(null)} />
            )}
          </div>

          {chat.sessionLoading ? (
            <div className="py-16 text-center">
              <Spinner label="Loading conversation" />
            </div>
          ) : chat.messages.length === 0 ? (
            <div className="mx-auto max-w-3xl px-4">
              <EmptyState icon={<BrainCircuit className="size-6" />} title="Ask your documents">
                {docsLoading ? (
                  <Spinner label="Checking documents" />
                ) : readyDocs.length === 0 ? (
                  <div className="space-y-4">
                    <p>
                      Upload at least one PDF to get started. Answers come only from your files.
                    </p>
                    <Link
                      href="/documents"
                      className="bg-accent text-accent-fg hover:bg-accent-hover inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium"
                    >
                      <Upload className="size-4" aria-hidden />
                      Upload documents
                    </Link>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <p>
                      Searching {readyDocs.length} document{readyDocs.length > 1 ? "s" : ""}. Every
                      answer cites the exact passages it used.
                    </p>
                    <div className="flex flex-col gap-2">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => send(s)}
                          className="border-border bg-surface hover:border-accent hover:text-accent rounded-xl border px-3 py-2 text-left text-sm transition-colors"
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </EmptyState>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
              {chat.messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  activeCitation={selection?.messageId === message.id ? selection.index : null}
                  onCitationClick={(index) => openCitation(message.id, index)}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <div className="mx-auto w-full max-w-3xl px-4 pb-4">
          <ChatComposer
            onSend={send}
            onStop={chat.stop}
            isStreaming={chat.isStreaming}
            documents={readyDocs}
            selectedDocIds={selectedDocIds}
            onSelectedDocIdsChange={setSelectedDocIds}
          />
          <p className="text-muted mt-2 text-center text-xs">
            Answers are generated only from your uploaded documents. Verify important details in the
            cited sources.
          </p>
        </div>
      </section>

      {/* Citations: side column on large screens, full-screen overlay on small ones */}
      {panelOpen && (
        <div className="fixed inset-0 z-30 lg:static lg:z-auto lg:block">
          <div
            className="absolute inset-0 bg-black/40 lg:hidden"
            onClick={() => setPanelOpen(false)}
          />
          <div className="absolute inset-y-0 right-0 w-full max-w-md lg:static lg:h-full lg:max-w-none">
            <CitationsPanel
              citations={panelCitations}
              activeIndex={activeIndex}
              onSelect={(index) => panelMessage && openCitation(panelMessage.id, index)}
              onClose={() => setPanelOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
