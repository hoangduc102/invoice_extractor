"use client";

import { useCallback, useEffect, useState } from "react";

import { InvoiceDetailPanel } from "@/components/InvoiceDetailPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadForm } from "@/components/UploadForm";
import {
  API_URL,
  ApiError,
  deleteInvoice,
  getInvoice,
  getStats,
  listInvoices,
  type InvoiceDetail,
  type InvoiceList,
  type InvoiceStatus,
  type Stats,
} from "@/lib/api";

const PAGE_SIZE = 10;

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function Home() {
  const [vendor, setVendor] = useState("");
  const [status, setStatus] = useState<InvoiceStatus | "">("");
  const [page, setPage] = useState(0);
  const [version, setVersion] = useState(0); // bump to refetch
  const [data, setData] = useState<InvoiceList | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<InvoiceDetail | null>(null);
  const debouncedVendor = useDebounced(vendor);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listInvoices({ vendor: debouncedVendor, status, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
      getStats(),
    ])
      .then(([list, s]) => {
        if (cancelled) return;
        setData(list);
        setStats(s);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [debouncedVendor, status, page, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  async function open(id: number) {
    try {
      setSelected(await getInvoice(id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this invoice?")) return;
    try {
      await deleteInvoice(id);
      setSelected(null);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-8 px-4 py-10 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Invoice Extractor</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Vision LLM + LangGraph self-correction · API <code className="text-xs">{API_URL}</code>
          </p>
        </div>
        {stats && (
          <dl className="flex gap-6 text-sm">
            {[
              ["Invoices", stats.invoice_count],
              ["Complete", stats.complete_count],
              ["Incomplete", stats.incomplete_count],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-zinc-500">{k}</dt>
                <dd className="text-xl font-semibold tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </header>

      <section className="rounded-2xl border border-zinc-200 p-5 dark:border-zinc-800">
        <h2 className="mb-4 font-medium">Upload invoice</h2>
        <UploadForm
          onExtracted={(inv) => {
            setSelected(inv);
            setPage(0);
            refresh();
          }}
        />
      </section>

      {selected && <InvoiceDetailPanel invoice={selected} onClose={() => setSelected(null)} onDelete={remove} />}

      <section className="rounded-2xl border border-zinc-200 dark:border-zinc-800">
        <div className="flex flex-wrap items-center gap-3 border-b border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="mr-auto font-medium">Extracted invoices</h2>
          <input
            value={vendor}
            onChange={(e) => {
              setVendor(e.target.value);
              setPage(0);
            }}
            placeholder="Filter by vendor…"
            aria-label="Filter by vendor"
            className="w-48 rounded-lg border border-zinc-300 bg-transparent px-3 py-1.5 text-sm dark:border-zinc-700"
          />
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as InvoiceStatus | "");
              setPage(0);
            }}
            aria-label="Filter by status"
            className="rounded-lg border border-zinc-300 bg-transparent px-3 py-1.5 text-sm dark:border-zinc-700"
          >
            <option value="">All statuses</option>
            <option value="complete">Complete</option>
            <option value="incomplete">Incomplete</option>
          </select>
        </div>

        {error && (
          <p role="alert" className="m-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Vendor</th>
                <th className="px-4 py-3 font-medium">Invoice #</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 text-right font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Extracted</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((inv) => (
                <tr
                  key={inv.id}
                  onClick={() => open(inv.id)}
                  className={`cursor-pointer border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900 ${
                    selected?.id === inv.id ? "bg-blue-50/60 dark:bg-blue-500/10" : ""
                  }`}
                >
                  <td className="px-4 py-3 font-medium">{inv.vendor_name ?? <span className="text-zinc-400">—</span>}</td>
                  <td className="px-4 py-3">{inv.invoice_number ?? "—"}</td>
                  <td className="px-4 py-3">{inv.invoice_date ?? "—"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {inv.total_raw ?? "—"}
                    {inv.currency && inv.total_raw && !inv.total_raw.includes(inv.currency) && (
                      <span className="ml-1 text-xs text-zinc-500">{inv.currency}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={inv.status} />
                  </td>
                  <td className="px-4 py-3 text-zinc-500">{formatDate(inv.created_at)}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-zinc-500">
                    {vendor || status ? "No invoices match these filters." : "No invoices yet. Upload one above."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {data && data.total > PAGE_SIZE && (
          <footer className="flex items-center justify-between border-t border-zinc-200 px-4 py-3 text-sm dark:border-zinc-800">
            <span className="text-zinc-500">
              {data.offset + 1}–{data.offset + data.items.length} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
              >
                Previous
              </button>
              <button
                disabled={page + 1 >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
              >
                Next
              </button>
            </div>
          </footer>
        )}
      </section>
    </main>
  );
}
