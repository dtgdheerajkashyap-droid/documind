"use client";

import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";

interface Props {
  onAdd: () => Promise<void>;
  variant?: "primary" | "secondary";
}

/** Adds the bundled sample PDFs, so first-time visitors can try the app without a file. */
export function SampleDocsButton({ onAdd, variant = "secondary" }: Props) {
  const [busy, setBusy] = useState(false);
  const styles =
    variant === "primary"
      ? "bg-accent text-accent-fg hover:bg-accent-hover"
      : "border-border bg-surface hover:border-accent hover:text-accent border";

  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await onAdd();
        } finally {
          setBusy(false);
        }
      }}
      className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:opacity-60 ${styles}`}
    >
      {busy ? (
        <Loader2 className="size-4 animate-spin" aria-hidden />
      ) : (
        <Sparkles className="size-4" aria-hidden />
      )}
      Try with sample documents
    </button>
  );
}
