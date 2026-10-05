"use client";

import { Loader2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { MAX_UPLOAD_MB } from "@/lib/format";
import type { RejectedFile, UploadResponse } from "@/lib/types";

interface Props {
  onUpload: (files: File[]) => Promise<UploadResponse>;
  maxSizeMb?: number;
}

/** Split files into those worth sending and those we can reject client-side. */
export function validateFiles(files: File[], maxSizeMb: number) {
  const accepted: File[] = [];
  const rejected: RejectedFile[] = [];
  for (const file of files) {
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) rejected.push({ filename: file.name, reason: "Only PDF files are supported." });
    else if (file.size > maxSizeMb * 1024 * 1024)
      rejected.push({ filename: file.name, reason: `File exceeds the ${maxSizeMb} MB limit.` });
    else if (file.size === 0) rejected.push({ filename: file.name, reason: "File is empty." });
    else accepted.push(file);
  }
  return { accepted, rejected };
}

export function UploadDropzone({ onUpload, maxSizeMb = MAX_UPLOAD_MB }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(fileList: FileList | File[]) {
    const { accepted, rejected: clientRejected } = validateFiles(Array.from(fileList), maxSizeMb);
    setRejected(clientRejected);
    setError(null);
    if (accepted.length === 0) return;

    setUploading(true);
    try {
      const response = await onUpload(accepted);
      setRejected([...clientRejected, ...response.rejected]);
    } catch (err) {
      const apiError = err instanceof ApiError ? err : null;
      const details = Array.isArray(apiError?.details) ? (apiError.details as RejectedFile[]) : [];
      if (details.length) setRejected([...clientRejected, ...details]);
      else setError(apiError?.message ?? "Upload failed. Please try again.");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload PDF files"
        aria-disabled={uploading}
        data-testid="dropzone"
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !uploading) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!uploading) void handleFiles(e.dataTransfer.files);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging
            ? "border-accent bg-accent-soft"
            : "border-border bg-surface hover:border-accent/60 hover:bg-surface-2"
        } ${uploading ? "cursor-wait opacity-70" : ""}`}
      >
        {uploading ? (
          <Loader2 className="text-accent mb-3 size-10 animate-spin" aria-hidden />
        ) : (
          <UploadCloud className="text-accent mb-3 size-10" aria-hidden />
        )}
        <p className="font-medium">
          {uploading ? "Uploading…" : "Drag & drop PDFs here, or click to browse"}
        </p>
        <p className="text-muted mt-1 text-sm">PDF only · up to {maxSizeMb} MB per file</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          data-testid="file-input"
          onChange={(e) => e.target.files && void handleFiles(e.target.files)}
        />
      </div>

      {error && (
        <p role="alert" className="text-danger mt-3 text-sm">
          {error}
        </p>
      )}
      {rejected.length > 0 && (
        <ul role="alert" className="mt-3 space-y-1 text-sm" aria-label="Rejected files">
          {rejected.map((r, i) => (
            <li key={`${r.filename}-${i}`} className="text-danger">
              <span className="font-medium">{r.filename}</span>: {r.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
