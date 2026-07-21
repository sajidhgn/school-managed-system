"use client";

import * as React from "react";
import type { FieldError } from "react-hook-form";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface FieldProps {
  label: string;
  htmlFor: string;
  error?: FieldError | { message?: string };
  hint?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

/**
 * Label + control + error, wired for accessibility.
 *
 * The error is rendered in an `aria-live` region and linked via
 * `aria-describedby`, so a screen reader announces a validation failure
 * instead of silently rejecting the form.
 */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  required,
  className,
  children,
}: FieldProps) {
  const errorId = `${htmlFor}-error`;
  const hintId = `${htmlFor}-hint`;
  const message = error?.message;

  return (
    <div className={cn("grid gap-1.5", className)}>
      <Label htmlFor={htmlFor} required={required}>
        {label}
      </Label>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            id: htmlFor,
            "aria-invalid": message ? true : undefined,
            "aria-describedby":
              [message ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") ||
              undefined,
          })
        : children}
      {hint && !message ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      <p id={errorId} role="alert" aria-live="polite" className="text-xs font-medium text-destructive empty:hidden">
        {message ?? ""}
      </p>
    </div>
  );
}

/** Non-field-specific form error, e.g. "Invalid email or password." */
export function FormError({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </div>
  );
}
