import { createSSEParser } from "@/lib/sse";
import { workspaceHeaders } from "@/lib/workspace";
import type {
  ChatRequest,
  Citation,
  DocumentItem,
  Health,
  SessionDetail,
  SessionSummary,
  UploadResponse,
} from "@/lib/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/** Error carrying the backend's `{error: {code, message, details}}` payload. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string = "error",
    public readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body?.error) {
      return new ApiError(body.error.message, response.status, body.error.code, body.error.details);
    }
  } catch {
    // Non-JSON error body.
  }
  return new ApiError(`Request failed with status ${response.status}`, response.status);
}

const UNREACHABLE_MESSAGE =
  "Cannot reach the DocuMind API. If it was idle, the free server may be waking up: " +
  "please try again in about a minute.";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...workspaceHeaders(), ...(init.headers as Record<string, string>) },
    });
  } catch {
    throw new ApiError(UNREACHABLE_MESSAGE, 0, "network_error");
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  listDocuments: () => request<DocumentItem[]>("/api/documents"),
  getDocument: (id: string) => request<DocumentItem>(`/api/documents/${id}`),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  uploadDocuments: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<UploadResponse>("/api/documents", { method: "POST", body: form });
  },
  addSampleDocuments: () => request<UploadResponse>("/api/documents/samples", { method: "POST" }),

  listSessions: () => request<SessionSummary[]>("/api/sessions"),
  getSession: (id: string) => request<SessionDetail>(`/api/sessions/${id}`),
  deleteSession: (id: string) => request<void>(`/api/sessions/${id}`, { method: "DELETE" }),
};

export interface ChatStreamHandlers {
  onMeta?: (data: { session_id: string; standalone_query: string }) => void;
  onToken?: (text: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onDone?: (data: {
    message_id: string;
    session_id: string;
    answer: string;
    refused: boolean;
  }) => void;
  onError?: (error: { code: string; message: string }) => void;
}

/** POST /api/chat and dispatch its Server-Sent Events to `handlers`. */
export async function streamChat(
  body: ChatRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: {
        ...workspaceHeaders(),
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(UNREACHABLE_MESSAGE, 0, "network_error");
  }
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new ApiError("Streaming is not supported by this browser.", 0);

  const parser = createSSEParser(({ event, data }) => {
    const payload = JSON.parse(data);
    switch (event) {
      case "meta":
        handlers.onMeta?.(payload);
        break;
      case "token":
        handlers.onToken?.(payload.text);
        break;
      case "citations":
        handlers.onCitations?.(payload.citations);
        break;
      case "done":
        handlers.onDone?.(payload);
        break;
      case "error":
        handlers.onError?.(payload);
        break;
    }
  });

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    parser.feed(value);
  }
  parser.flush();
}
