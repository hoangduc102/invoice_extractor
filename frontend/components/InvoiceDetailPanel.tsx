"use client";

import type { InvoiceDetail } from "@/lib/api";

import { StatusBadge } from "./StatusBadge";

const KEY_FIELDS = ["INVOICE_NUMBER", "DATE", "DUE_DATE", "TOTAL", "CURRENCY", "VENDOR_NAME", "CUSTOMER_NAME"];

function label(key: string) {
  return key.replaceAll("_", " ").toLowerCase();
}

export function InvoiceDetailPanel({
  invoice,
  onClose,
  onDelete,
}: {
  invoice: InvoiceDetail;
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  const otherFields = Object.entries(invoice.fields).filter(([k]) => !KEY_FIELDS.includes(k));
  const missing = new Set(invoice.missing_fields);

  return (
    <section className="rounded-2xl border border-zinc-200 p-5 dark:border-zinc-800">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {invoice.vendor_name ?? "Unknown vendor"}
            {invoice.invoice_number && <span className="ml-2 font-normal text-zinc-500">#{invoice.invoice_number}</span>}
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            {invoice.filename} · {invoice.model_name} · {invoice.retry_count} self-correction
            {invoice.retry_count === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={invoice.status} />
          <button
            onClick={() => onDelete(invoice.id)}
            className="rounded-lg px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10"
          >
            Delete
          </button>
          <button
            onClick={onClose}
            aria-label="Close details"
            className="rounded-lg px-2.5 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            Close
          </button>
        </div>
      </header>

      {invoice.missing_fields.length > 0 && (
        <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
          Still missing after retries: {invoice.missing_fields.join(", ")}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {KEY_FIELDS.map((key) => {
          const value = invoice.fields[key];
          const absent = !value || value === "N/A";
          return (
            <div
              key={key}
              className={`rounded-lg p-3 ${missing.has(key) ? "bg-amber-50 dark:bg-amber-500/10" : "bg-zinc-50 dark:bg-zinc-900"}`}
            >
              <dt className="text-xs capitalize text-zinc-500">{label(key)}</dt>
              <dd className={`mt-1 break-words text-sm font-medium ${absent ? "text-zinc-400" : ""}`}>
                {absent ? "—" : value}
              </dd>
            </div>
          );
        })}
      </dl>

      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">All fields</summary>
        <table className="mt-2 w-full text-left">
          <tbody>
            {otherFields.map(([k, v]) => (
              <tr key={k} className="border-t border-zinc-100 dark:border-zinc-800">
                <th className="w-48 py-1.5 pr-3 align-top font-normal capitalize text-zinc-500">{label(k)}</th>
                <td className="py-1.5 whitespace-pre-wrap">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">Raw model output</summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-zinc-50 p-3 text-xs dark:bg-zinc-900">
          {invoice.raw_text || "(empty)"}
        </pre>
      </details>
    </section>
  );
}
