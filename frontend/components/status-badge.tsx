import { cn } from "@/lib/utils";

const STYLES: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700 border border-border",
  running: "bg-accent/10 text-accent border border-accent/30",
  completed: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  failed: "bg-red-50 text-red-700 border border-red-200",
  cancelled: "bg-amber-50 text-amber-700 border border-amber-200"
};

export function StatusBadge({ status }: { status: string }) {
  const key = status?.toLowerCase?.() || "queued";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium capitalize",
        STYLES[key] || "bg-slate-100 text-slate-700 border border-border"
      )}
    >
      {status || "queued"}
    </span>
  );
}
