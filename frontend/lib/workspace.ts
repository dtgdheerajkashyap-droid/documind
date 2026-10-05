/**
 * Anonymous per-browser workspace.
 *
 * A random UUID is created on first visit and kept in localStorage. It is sent
 * with every API request as `X-Workspace-Id`, so each visitor only sees their own
 * documents and chats, without needing an account.
 */

const STORAGE_KEY = "documind-workspace-id";
let memoryId: string | null = null;

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  // Fallback for older browsers / non-secure contexts.
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (Number(c) ^ ((Math.random() * 16) >> (Number(c) / 4))).toString(16),
  );
}

export function getWorkspaceId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = window.localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = randomId();
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    // Storage blocked (e.g. private mode): keep one ID for this page session.
    memoryId ??= randomId();
    return memoryId;
  }
}

export function workspaceHeaders(): Record<string, string> {
  const id = getWorkspaceId();
  return id ? { "X-Workspace-Id": id } : {};
}
