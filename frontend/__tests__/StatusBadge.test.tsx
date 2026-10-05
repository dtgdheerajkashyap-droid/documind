import { render, screen } from "@testing-library/react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import type { DocumentStatus } from "@/lib/types";

describe("StatusBadge", () => {
  it.each<[DocumentStatus, string]>([
    ["queued", "Queued"],
    ["processing", "Processing"],
    ["ready", "Ready"],
    ["failed", "Failed"],
  ])("renders the %s status", (status, label) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute("data-status", status);
  });

  it("shows the failure reason as a tooltip", () => {
    render(<StatusBadge status="failed" title="No extractable text" />);
    expect(screen.getByText("Failed")).toHaveAttribute("title", "No extractable text");
  });
});
