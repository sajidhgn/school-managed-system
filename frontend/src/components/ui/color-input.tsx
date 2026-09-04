"use client";

import * as React from "react";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const THEME_COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/;

/** Matches the API's palette cap (`ThemeColors` in the tenancy schemas). */
export const MAX_THEME_COLORS = 5;

/**
 * A `#RRGGBB` accent-colour field: native picker + hex text + clear.
 *
 * Empty is a real state, not an error — it means "inherit" (a branch falling back
 * to its organization's branding) — which is why this isn't just an
 * `<input type="color">`: that control cannot be empty, so it can't express
 * "no colour of our own". The picker only mirrors the text value when the text
 * holds a valid colour; clearing goes through the X.
 */
export function ColorInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const valid = THEME_COLOR_PATTERN.test(value);

  return (
    <div className="flex items-center gap-2">
      <input
        type="color"
        aria-label="Pick a colour"
        value={valid ? value : "#94a3b8"}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-10 shrink-0 cursor-pointer rounded-md border border-border bg-background p-1 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <Input
        id={id}
        value={value}
        disabled={disabled}
        placeholder="#1D4ED8"
        maxLength={7}
        onChange={(event) => onChange(event.target.value.trim())}
        className="w-32 font-mono"
      />
      {value && !disabled ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="rounded-sm p-1 text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
          <span className="sr-only">Clear colour</span>
        </button>
      ) : null}
    </div>
  );
}

/**
 * An ordered palette of theme colours.
 *
 * Order carries meaning downstream — the first colour is the primary, the
 * second the secondary, and card designs read them by position — so this is a
 * list, not a set. Clearing a row (the ColorInput's X) removes it: an empty
 * slot in the middle of a palette would silently shift what "secondary" means.
 */
export function ColorListInput({
  values,
  onChange,
  disabled,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid gap-2">
      {values.map((value, index) => (
        <div key={index} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs text-muted-foreground">
            {index === 0 ? "Primary" : index === 1 ? "Secondary" : `Colour ${index + 1}`}
          </span>
          <ColorInput
            value={value}
            disabled={disabled}
            onChange={(next) =>
              onChange(
                next === ""
                  ? values.filter((_, i) => i !== index)
                  : values.map((v, i) => (i === index ? next : v)),
              )
            }
          />
        </div>
      ))}
      {!disabled && values.length < MAX_THEME_COLORS ? (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange([...values, "#1D4ED8"])}
          >
            <Plus className="size-4" aria-hidden />
            Add colour
          </Button>
        </div>
      ) : null}
    </div>
  );
}
