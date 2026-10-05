import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatMessage } from "@/components/chat/ChatMessage";
import type { Citation, UiMessage } from "@/lib/types";

const citation = (index: number, page: number): Citation => ({
  index,
  chunk_id: `c${index}`,
  document_id: "d1",
  filename: "handbook.pdf",
  page,
  chunk_index: index,
  text: `Passage ${index}`,
  score: 0.8,
});

const assistant = (overrides: Partial<UiMessage> = {}): UiMessage => ({
  id: "m1",
  role: "assistant",
  content: "Refunds are allowed within 30 days [1]. Opened bags: 7 days [2].",
  citations: [citation(1, 2), citation(2, 3)],
  status: "done",
  ...overrides,
});

describe("ChatMessage", () => {
  it("turns citation markers into clickable buttons", async () => {
    const onCitationClick = vi.fn();
    render(<ChatMessage message={assistant()} onCitationClick={onCitationClick} />);

    await userEvent.click(screen.getByRole("button", { name: "Show source 2" }));

    expect(onCitationClick).toHaveBeenCalledWith(2);
    expect(screen.getByText(/Refunds are allowed within 30 days/)).toBeInTheDocument();
  });

  it("lists sources with filename and page", async () => {
    const onCitationClick = vi.fn();
    render(<ChatMessage message={assistant()} onCitationClick={onCitationClick} />);

    const chip = screen.getByRole("button", { name: "[1] handbook.pdf · p. 2" });
    await userEvent.click(chip);
    expect(onCitationClick).toHaveBeenCalledWith(1);
  });

  it("leaves unknown markers as plain text", () => {
    render(<ChatMessage message={assistant({ content: "See [7].", citations: [] })} />);
    expect(screen.getByText("See [7].")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a searching indicator before the first token arrives", () => {
    render(
      <ChatMessage message={assistant({ content: "", citations: [], status: "streaming" })} />,
    );
    expect(screen.getByText(/Searching your documents/)).toBeInTheDocument();
  });

  it("shows stream errors", () => {
    render(
      <ChatMessage
        message={assistant({ status: "error", error: "Gemini request failed", citations: [] })}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Gemini request failed");
  });

  it("renders user messages as plain text", () => {
    render(
      <ChatMessage
        message={{ id: "u1", role: "user", content: "Hi [1]", citations: [], status: "done" }}
      />,
    );
    expect(screen.getByText("Hi [1]")).toBeInTheDocument();
  });
});
