import { type ReactNode } from "react";
import { cn } from "../../lib/utils";

type CardProps = {
  children: ReactNode;
  className?: string;
  glow?: "cyan" | "red" | "none";
};

export function Card({ children, className, glow = "none" }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border bg-slate-900/60 backdrop-blur-md p-6 transition-all duration-300",
        glow === "cyan" && "border-cyan-500/30 shadow-[0_0_24px_-4px_rgba(0,240,255,0.15)]",
        glow === "red" && "border-red-500/30 shadow-[0_0_24px_-4px_rgba(239,68,68,0.15)]",
        glow === "none" && "border-slate-800/80 shadow-[0_8px_32px_rgba(0,0,0,0.4)]",
        className,
      )}
    >
      {children}
    </div>
  );
}
