import { api } from "@/lib/api";
import { getWorkspaceId, workspaceHeaders } from "@/lib/workspace";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("workspace id", () => {
  beforeEach(() => localStorage.clear());

  it("is a random UUID that persists across calls", () => {
    const id = getWorkspaceId();
    expect(id).toMatch(UUID);
    expect(getWorkspaceId()).toBe(id);
    expect(localStorage.getItem("documind-workspace-id")).toBe(id);
  });

  it("differs between browsers (fresh storage)", () => {
    const first = getWorkspaceId();
    localStorage.clear();
    expect(getWorkspaceId()).not.toBe(first);
  });

  it("is sent with every API request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.listDocuments();

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers["X-Workspace-Id"]).toBe(workspaceHeaders()["X-Workspace-Id"]);
    expect(headers["X-Workspace-Id"]).toMatch(UUID);
    vi.unstubAllGlobals();
  });

  it("explains a cold start when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.listDocuments()).rejects.toThrow(/waking up/);
    vi.unstubAllGlobals();
  });
});
