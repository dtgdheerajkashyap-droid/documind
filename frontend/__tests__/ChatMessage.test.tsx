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

    const card = screen.getByRole("button", { name: "Source 1: handbook.pdf, page 2" });
    expect(card).toHaveTextContent("Passage 1");
    await userEvent.click(card);
    expect(onCitationClick).toHaveBeenCalledWith(1);
    expect(screen.getByText("Grounded in 2 sources")).toBeInTheDocument();
  });

  it("renders Markdown structure with citations inside it", async () => {
    const onCitationClick = vi.fn();
    const content = [
      "Program 4 trains an **autoencoder** [1].",
      "",
      "### Steps",
      "1. Load the `DigitDataset` images [1].",
      "2. Train with `adam` [2].",
      "",
      "```matlab",
      "net = trainNetwork(XTrain, YTrain, layers, options);",
      "```",
    ].join("\n");
    render(<ChatMessage message={assistant({ content })} onCitationClick={onCitationClick} />);

    expect(screen.getByRole("heading", { name: "Steps" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("autoencoder").tagName).toBe("STRONG");
    expect(screen.getByText(/net = trainNetwork/).closest("pre")).not.toBeNull();
    expect(screen.queryByText(/\*\*|###|```/)).not.toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Show source 2" })[0]);
    expect(onCitationClick).toHaveBeenCalledWith(2);
  });

  it("shows a refusal as a not-found notice without sources or copy", () => {
    render(
      <ChatMessage
        message={assistant({
          content: "I couldn't find this in your documents.",
          citations: [],
          refused: true,
        })}
      />,
    );
    expect(screen.getByText("I couldn't find this in your documents.")).toBeInTheDocument();
    expect(screen.getByText(/Try rephrasing/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy/ })).not.toBeInTheDocument();
  });

  it("copies the answer without citation markers or Markdown", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    render(<ChatMessage message={assistant({ content: "It is **30 days** [1]." })} />);

    await user.click(screen.getByRole("button", { name: "Copy answer" }));

    expect(writeText).toHaveBeenCalledWith("It is 30 days.");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("leaves unknown markers as plain text", () => {
    render(<ChatMessage message={assistant({ content: "See [7].", citations: [] })} />);
    expect(screen.getByText("See [7].")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /source/i })).not.toBeInTheDocument();
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
