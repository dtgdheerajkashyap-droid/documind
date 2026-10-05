import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";

import type { DocumentStatus } from "@/lib/types";

const STYLES: Record<DocumentStatus, { label: string; className: string; Icon: typeof Clock }> = {
  queued: {
    label: "Queued",
    className: "bg-surface-2 text-muted",
    Icon: Clock,
  },
  processing: {
    label: "Processing",
    className: "bg-accent-soft text-accent",
    Icon: Loader2,
  },
  ready: {
    label: "Ready",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    Icon: CheckCircle2,
  },
  failed: {
    label: "Failed",
    className: "bg-danger-soft text-danger",
    Icon: AlertCircle,
  },
};

export function StatusBadge({ status, title }: { status: DocumentStatus; title?: string }) {
  const { label, className, Icon } = STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
      title={title}
      data-status={status}
    >
      <Icon className={`size-3.5 ${status === "processing" ? "animate-spin" : ""}`} aria-hidden />
      {label}
    </span>
  );
}
