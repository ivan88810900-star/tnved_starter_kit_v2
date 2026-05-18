import { cn } from "../../lib/utils";

type Variant = "cyan" | "red" | "amber" | "emerald" | "violet" | "slate";

type BadgeProps = {
  label: string;
  variant?: Variant;
  className?: string;
};

const VARIANTS: Record<Variant, string> = {
  cyan: "bg-cyan-400/10 text-cyan-300 border-cyan-400/25",
  red: "bg-red-500/10 text-red-400 border-red-500/25",
  amber: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
  violet: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  slate: "bg-slate-700/60 text-slate-300 border-slate-600/40",
};

export function Badge({ label, variant = "slate", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        VARIANTS[variant],
        className,
      )}
    >
      {label}
    </span>
  );
}
