"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, extractInvoice, getConfig, type BackendConfig, type InvoiceDetail } from "@/lib/api";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp";
const MAX_BYTES = 10 * 1024 * 1024;

export function UploadForm({ onExtracted }: { onExtracted: (invoice: InvoiceDetail) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState(""); // empty = server default
  const [backend, setBackend] = useState<BackendConfig | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConfig()
      .then(setBackend)
      .catch(() => {}); // the table already shows a connection error
  }, []);

  function pick(f: File | undefined) {
    setError(null);
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setError("File is larger than 10 MB.");
      return;
    }
    setFile(f);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onExtracted(await extractInvoice(file, model));
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status ? `${err.status}: ` : ""}${err.message}` : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging
            ? "border-blue-500 bg-blue-50 dark:bg-blue-500/10"
            : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-500"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <span className="text-sm font-medium">
          {file ? file.name : "Drop an invoice here, or click to choose"}
        </span>
        <span className="mt-1 text-xs text-zinc-500">
          {file ? `${(file.size / 1024).toFixed(0)} KB` : "PDF, PNG, JPEG or WEBP · max 10 MB"}
        </span>
      </label>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm">
          <span className="mb-1 block text-zinc-600 dark:text-zinc-400">
            Model{backend && <> · {backend.provider_label}</>}
          </span>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={backend ? `${backend.default_model} (default)` : "server default"}
            className="w-full rounded-lg border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
          />
        </label>
        <button
          type="submit"
          disabled={!file || busy}
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Extracting…" : "Extract"}
        </button>
      </div>

      {busy && (
        <p className="text-xs text-zinc-500">
          Running the self-correcting LangGraph pipeline.{" "}
          {backend?.provider === "ollama" ? "Local models can take 30–90 s per page." : "Usually a few seconds."}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </p>
      )}
    </form>
  );
}
