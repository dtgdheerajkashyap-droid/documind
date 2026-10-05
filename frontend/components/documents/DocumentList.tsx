"use client";

import { FileText, Trash2 } from "lucide-react";
import { useState } from "react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import type { DocumentItem } from "@/lib/types";

interface Props {
  documents: DocumentItem[];
  onDelete: (id: string) => void;
}

function DeleteButton({ filename, onConfirm }: { filename: string; onConfirm: () => void }) {
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <span className="flex items-center gap-1">
        <button
          type="button"
          onClick={onConfirm}
          className="bg-danger rounded-md px-2 py-1 text-xs font-medium text-white hover:opacity-90"
        >
          Delete
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="text-muted hover:text-text rounded-md px-2 py-1 text-xs"
        >
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      aria-label={`Delete ${filename}`}
      className="text-muted hover:bg-danger-soft hover:text-danger rounded-md p-1.5 transition-colors"
    >
      <Trash2 className="size-4" />
    </button>
  );
}

export function DocumentList({ documents, onDelete }: Props) {
  return (
    <div className="border-border bg-surface overflow-hidden rounded-2xl border">
      <table className="w-full text-sm">
        <thead className="bg-surface-2 text-muted hidden text-left text-xs tracking-wide uppercase sm:table-header-group">
          <tr>
            <th className="px-4 py-2.5 font-medium">Document</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="px-4 py-2.5 text-right font-medium">Pages</th>
            <th className="px-4 py-2.5 text-right font-medium">Chunks</th>
            <th className="px-4 py-2.5 font-medium">Uploaded</th>
            <th className="px-4 py-2.5">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          {documents.map((doc) => (
            <tr
              key={doc.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:table-row"
            >
              <td className="flex min-w-0 flex-1 items-center gap-3 sm:px-4 sm:py-3">
                <FileText className="text-muted size-5 shrink-0" aria-hidden />
                <div className="min-w-0">
                  <p className="truncate font-medium" title={doc.filename}>
                    {doc.filename}
                  </p>
                  <p className="text-muted text-xs">
                    {formatBytes(doc.file_size)}
                    <span className="sm:hidden">
                      {doc.page_count != null && ` · ${doc.page_count} pages`}
                      {doc.status === "ready" && ` · ${doc.chunk_count} chunks`}
                    </span>
                  </p>
                  {doc.status === "failed" && doc.error_message && (
                    <p className="text-danger mt-0.5 text-xs">{doc.error_message}</p>
                  )}
                </div>
              </td>
              <td className="sm:px-4 sm:py-3">
                <StatusBadge status={doc.status} title={doc.error_message ?? undefined} />
              </td>
              <td className="hidden px-4 py-3 text-right tabular-nums sm:table-cell">
                {doc.page_count ?? "–"}
              </td>
              <td className="hidden px-4 py-3 text-right tabular-nums sm:table-cell">
                {doc.status === "ready" ? doc.chunk_count : "–"}
              </td>
              <td className="text-muted hidden px-4 py-3 whitespace-nowrap sm:table-cell">
                {formatRelativeTime(doc.created_at)}
              </td>
              <td className="sm:px-4 sm:py-3 sm:text-right">
                <DeleteButton filename={doc.filename} onConfirm={() => onDelete(doc.id)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
