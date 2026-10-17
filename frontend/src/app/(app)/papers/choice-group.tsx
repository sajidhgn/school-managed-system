"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A row of mutually exclusive buttons -- a radio group that shows every choice at
 * once. Used for the short, fixed lists on the paper forms.
 */
export function ChoiceGroup<T extends string>({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string; lang?: string }[];
  hint?: string;
}) {
  const id = React.useId();
  return (
    <div className="grid content-start gap-1.5">
      <span id={id} className="text-sm font-medium leading-none">
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={id}
        className="inline-flex w-full rounded-md border border-input bg-card p-0.5 shadow-sm"
      >
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              lang={option.lang}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-8 flex-1 rounded-[5px] px-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "bg-primary font-medium text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
