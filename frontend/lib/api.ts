// Typed client for the FastAPI backend (api/main.py).

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type InvoiceStatus = "complete" | "incomplete";

export interface InvoiceSummary {
  id: number;
  created_at: string;
  filename: string;
  invoice_number: string | null;
  vendor_name: string | null;
  invoice_date: string | null;
  currency: string | null;
  total_raw: string | null;
  total_amount: string | null; // Decimal serialized as string
  status: InvoiceStatus;
}

export interface InvoiceDetail extends InvoiceSummary {
  content_type: string;
  model_name: string;
  retry_count: number;
  missing_fields: string[];
  fields: Record<string, string>;
  raw_text: string;
}

export interface InvoiceList {
  total: number;
  limit: number;
  offset: number;
  items: InvoiceSummary[];
}

export interface Stats {
  invoice_count: number;
  complete_count: number;
  incomplete_count: number;
  top_vendors: { vendor_name: string; invoice_count: number; total_amount: string | null }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export function extractInvoice(file: File, modelName: string): Promise<InvoiceDetail> {
  const form = new FormData();
  form.append("file", file);
  if (modelName.trim()) form.append("model_name", modelName.trim());
  return request("/invoices/extract", { method: "POST", body: form });
}

export function listInvoices(params: {
  vendor?: string;
  status?: InvoiceStatus | "";
  limit: number;
  offset: number;
}): Promise<InvoiceList> {
  const qs = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.vendor) qs.set("vendor", params.vendor);
  if (params.status) qs.set("status", params.status);
  return request(`/invoices?${qs}`);
}

export const getInvoice = (id: number) => request<InvoiceDetail>(`/invoices/${id}`);
export const deleteInvoice = (id: number) => request<void>(`/invoices/${id}`, { method: "DELETE" });
export const getStats = () => request<Stats>("/invoices/stats");

export interface BackendConfig {
  provider: string;
  provider_label: string;
  default_model: string;
}
export const getConfig = () => request<BackendConfig>("/config");
