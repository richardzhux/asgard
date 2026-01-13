import * as React from "react";
import { cn } from "@/lib/utils";

type SwitchProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Switch({ className, ...props }: SwitchProps) {
  return (
    <label className={cn("inline-flex items-center gap-2 cursor-pointer select-none", className)}>
      <input type="checkbox" className="peer sr-only" {...props} />
      <span className="relative h-5 w-10 rounded-full border border-border bg-muted transition peer-checked:bg-accent/90">
        <span className="absolute left-[2px] top-[2px] h-4 w-4 rounded-full bg-white shadow-sm transition peer-checked:translate-x-5" />
      </span>
    </label>
  );
}
