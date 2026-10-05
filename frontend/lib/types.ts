/** Types mirroring the backend's Pydantic schemas. */

export type DocumentStatus = "queued" | "processing" | "ready" | "failed";

export interface DocumentItem {
  id: string;
  filename: string;
  file_size: number;
  status: DocumentStatus;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface RejectedFile {
  filename: string;
  reason: string;
}

export interface UploadResponse {
  documents: DocumentItem[];
  rejected: RejectedFile[];
}

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number;
  chunk_index: number;
  text: string;
  score: number;
}

export type Role = "user" | "assistant";

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface MessageOut {
  id: string;
  role: Role;
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface SessionDetail extends SessionSummary {
  messages: MessageOut[];
}

export interface Health {
  status: string;
  version: string;
  database: boolean;
  vector_store: boolean;
  llm_provider: string;
  llm_configured: boolean;
  embedding_model: string;
}

export interface ChatRequest {
  question: string;
  session_id?: string | null;
  document_ids?: string[] | null;
}

/** A message as rendered in the chat UI (may still be streaming). */
export interface UiMessage {
  id: string;
  role: Role;
  content: string;
  citations: Citation[];
  status: "streaming" | "done" | "error";
  refused?: boolean;
  error?: string;
}
