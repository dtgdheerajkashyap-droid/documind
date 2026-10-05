"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, streamChat } from "@/lib/api";
import type { SessionSummary, UiMessage } from "@/lib/types";

let tempCounter = 0;
const tempId = () => `tmp-${Date.now()}-${tempCounter++}`;

const errorMessage = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Please try again.";

/** Chat state: sessions, the active conversation, and streaming answers. */
export function useChat() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await api.listSessions());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listSessions()
      .then((list) => !cancelled && setSessions(list))
      .catch((err) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setSessionsLoading(false));
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  const selectSession = useCallback(async (id: string) => {
    abortRef.current?.abort();
    setActiveSessionId(id);
    setSessionLoading(true);
    setError(null);
    try {
      const detail = await api.getSession(id);
      setMessages(
        detail.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations,
          status: "done",
          refused: m.role === "assistant" && m.citations.length === 0,
        })),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSessionLoading(false);
    }
  }, []);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setActiveSessionId(null);
    setMessages([]);
    setError(null);
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await api.deleteSession(id);
        setSessions((list) => list.filter((s) => s.id !== id));
        if (id === activeSessionId) newChat();
      } catch (err) {
        setError(errorMessage(err));
      }
    },
    [activeSessionId, newChat],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const send = useCallback(
    async (question: string, documentIds: string[] = []) => {
      const text = question.trim();
      if (!text || isStreaming) return;

      const assistantId = tempId();
      setError(null);
      setMessages((list) => [
        ...list,
        { id: tempId(), role: "user", content: text, citations: [], status: "done" },
        { id: assistantId, role: "assistant", content: "", citations: [], status: "streaming" },
      ]);
      const update = (patch: (m: UiMessage) => Partial<UiMessage>) =>
        setMessages((list) => list.map((m) => (m.id === assistantId ? { ...m, ...patch(m) } : m)));

      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);
      try {
        await streamChat(
          {
            question: text,
            session_id: activeSessionId,
            document_ids: documentIds.length ? documentIds : null,
          },
          {
            onMeta: ({ session_id }) => setActiveSessionId(session_id),
            onToken: (token) => update((m) => ({ content: m.content + token })),
            onCitations: (citations) => update(() => ({ citations })),
            onDone: ({ answer, refused }) =>
              update(() => ({ content: answer, refused, status: "done" })),
            onError: ({ message }) => update(() => ({ status: "error", error: message })),
          },
          controller.signal,
        );
        // Stream closed without a terminal event (e.g. connection dropped).
        update((m) =>
          m.status === "streaming"
            ? { status: "error", error: "The connection closed before the answer finished." }
            : {},
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          update((m) => ({ status: "done", content: m.content || "(stopped)" }));
        } else {
          update(() => ({ status: "error", error: errorMessage(err) }));
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setIsStreaming(false);
        void refreshSessions();
      }
    },
    [activeSessionId, isStreaming, refreshSessions],
  );

  return {
    sessions,
    sessionsLoading,
    activeSessionId,
    messages,
    sessionLoading,
    isStreaming,
    error,
    setError,
    send,
    stop,
    newChat,
    selectSession,
    deleteSession,
  };
}
