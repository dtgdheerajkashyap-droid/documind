"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { DocumentItem, UploadResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;

const errorMessage = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Please try again.";

/** Document list with upload/delete, polling while any document is still being ingested. */
export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const docs = await api.listDocuments();
      setDocuments(docs);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listDocuments()
      .then((docs) => !cancelled && (setDocuments(docs), setError(null)))
      .catch((err) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const hasPending = documents.some((d) => d.status === "queued" || d.status === "processing");

  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasPending, refresh]);

  const upload = useCallback(async (files: File[]): Promise<UploadResponse> => {
    const response = await api.uploadDocuments(files);
    setDocuments((current) => [...response.documents, ...current]);
    return response;
  }, []);

  const remove = useCallback(
    async (id: string) => {
      const previous = documents;
      setDocuments((current) => current.filter((d) => d.id !== id));
      try {
        await api.deleteDocument(id);
      } catch (err) {
        setDocuments(previous);
        setError(errorMessage(err));
      }
    },
    [documents],
  );

  return { documents, loading, error, setError, refresh, upload, remove };
}
