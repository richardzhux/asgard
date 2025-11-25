import * as React from "react";
import { cn } from "@/lib/utils";

type SwitchProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Switch({ className, ...props }: SwitchProps) {
  return (
    <label className={cn("inline-flex items-center gap-2 cursor-pointer select-none", className)}>
      <input
        type="checkbox"
        className="peer sr-only"
        {...props}
      />
      <span className="h-5 w-9 rounded-full border border-border bg-muted relative transition peer-checked:bg-accent">
        <span className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition peer-checked:translate-x-4" />
      </span>
    </label>
  );
}
