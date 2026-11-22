import type { InvoiceStatus } from "@/lib/api";

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const complete = status === "complete";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        complete
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300"
          : "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${complete ? "bg-emerald-500" : "bg-amber-500"}`} />
      {complete ? "Complete" : "Incomplete"}
    </span>
  );
}
