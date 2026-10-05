"use client";

import { FolderOpen } from "lucide-react";

import { DocumentList } from "@/components/documents/DocumentList";
import { UploadDropzone } from "@/components/documents/UploadDropzone";
import { EmptyState, ErrorBanner, Spinner } from "@/components/ui/Feedback";
import { useDocuments } from "@/hooks/useDocuments";

export function DocumentsView() {
  const { documents, loading, error, setError, upload, remove } = useDocuments();
  const ready = documents.filter((d) => d.status === "ready").length;

  return (
    <div className="mx-auto w-full max-w-5xl flex-1 overflow-y-auto px-4 py-6 sm:px-6 sm:py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="text-muted mt-1 text-sm">
          Upload PDFs to build your knowledge base. DocuMind answers only from these files.
        </p>
      </div>

      <UploadDropzone onUpload={upload} />

      <section className="mt-8" aria-labelledby="library-heading">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="library-heading" className="font-semibold">
            Library
          </h2>
          {documents.length > 0 && (
            <span className="text-muted text-sm">
              {ready} of {documents.length} ready
            </span>
          )}
        </div>

        {error && (
          <div className="mb-3">
            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </div>
        )}

        {loading ? (
          <div className="py-10 text-center">
            <Spinner label="Loading documents" />
          </div>
        ) : documents.length === 0 ? (
          !error && (
            <EmptyState icon={<FolderOpen className="size-6" />} title="No documents yet">
              Upload a PDF above. It will be split into passages, embedded, and indexed so you can
              ask questions about it.
            </EmptyState>
          )
        ) : (
          <DocumentList documents={documents} onDelete={(id) => void remove(id)} />
        )}
      </section>
    </div>
  );
}
