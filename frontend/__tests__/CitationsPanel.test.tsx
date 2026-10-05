import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CitationsPanel } from "@/components/chat/CitationsPanel";
import type { Citation } from "@/lib/types";

const citations: Citation[] = [
  {
    index: 1,
    chunk_id: "a",
    document_id: "d1",
    filename: "policy.pdf",
    page: 4,
    chunk_index: 7,
    text: "Customers may return unopened bags within 30 days.",
    score: 0.71,
  },
  {
    index: 3,
    chunk_id: "b",
    document_id: "d2",
    filename: "benefits.pdf",
    page: 1,
    chunk_index: 0,
    text: "Baristas receive 20 days of paid vacation.",
    score: 0.55,
  },
];

describe("CitationsPanel", () => {
  it("shows passage, filename, page and relevance for each citation", () => {
    render(
      <CitationsPanel citations={citations} activeIndex={1} onSelect={vi.fn()} onClose={vi.fn()} />,
    );

    expect(screen.getByText("policy.pdf")).toBeInTheDocument();
    expect(screen.getByText("Page 4")).toBeInTheDocument();
    expect(screen.getByText("Relevance 71%")).toBeInTheDocument();
    expect(screen.getByText(/return unopened bags within 30 days/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /policy\.pdf/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("button", { name: /benefits\.pdf/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("selects a citation and closes", async () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <CitationsPanel
        citations={citations}
        activeIndex={null}
        onSelect={onSelect}
        onClose={onClose}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /benefits\.pdf/ }));
    expect(onSelect).toHaveBeenCalledWith(3);

    await userEvent.click(screen.getByRole("button", { name: "Close sources panel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("explains how to use the panel when empty", () => {
    render(
      <CitationsPanel citations={[]} activeIndex={null} onSelect={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.getByText(/Click a citation/)).toBeInTheDocument();
  });
});
