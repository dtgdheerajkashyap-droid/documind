import { AlertTriangle, Loader2, X } from "lucide-react";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="text-muted inline-flex items-center gap-2 text-sm" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </span>
  );
}

export function ErrorBanner({
  message,
  onDismiss,
  tone = "danger",
}: {
  message: string;
  onDismiss?: () => void;
  tone?: "danger" | "warning";
}) {
  const colors =
    tone === "danger"
      ? "bg-danger-soft text-danger border-danger/30"
      : "bg-warning-soft text-warning border-warning/30";
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${colors}`}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="flex-1">{message}</p>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="opacity-70 hover:opacity-100"
        >
          <X className="size-4" />
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="bg-accent-soft text-accent mb-4 flex size-12 items-center justify-center rounded-2xl">
        {icon}
      </div>
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <div className="text-muted mt-2 max-w-md text-sm">{children}</div>}
    </div>
  );
}
