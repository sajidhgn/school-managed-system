"use client";

import type { Route } from "next";
import { School } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { authRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { SchoolRead } from "@/lib/api/types";

/**
 * Choose which campus an ORG-LEVEL user is working in.
 *
 * Deliberately NOT the same control as `ContextPicker`, even though they look alike.
 * That one switches which membership you act as and re-mints the session; this one
 * changes nothing about who you are. The principal already administers every campus
 * here — this only says which of them the school-scoped pages should render.
 *
 * The distinction is worth two components rather than a flag, because getting it
 * wrong in either direction is bad: a campus change that silently re-issued a token
 * would drop the user's org-wide reach, and a membership switch that only set a
 * cookie would show one organisation's chrome around another's data.
 */
export function SchoolPicker({
  schools,
  activeSchoolId = null,
  redirectTo = "/dashboard",
  onPicked,
}: {
  schools: SchoolRead[];
  activeSchoolId?: string | null;
  /** Runtime path, so it is cast at the push site. */
  redirectTo?: string;
  onPicked?: () => void;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function select(schoolId: string) {
    setBusy(schoolId);
    setError(null);
    try {
      await authRequest("/school", { school_id: schoolId });
      onPicked?.();
      router.refresh();
      router.push(redirectTo as Route);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t.errors.generic);
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4">
      <ul className="grid gap-2">
        {schools.map((school) => (
          <li key={school.id}>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => select(school.id)}
              aria-current={school.id === activeSchoolId ? "true" : undefined}
              className="flex w-full items-center gap-3 rounded-lg border border-border bg-card p-3 text-start transition-colors hover:border-primary hover:bg-accent disabled:opacity-60 aria-[current]:border-primary"
            >
              <span className="grid size-9 shrink-0 place-items-center rounded-md bg-accent text-accent-foreground">
                <School className="size-4" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{school.name}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {school.code}
                  {school.city ? ` · ${school.city}` : ""}
                </span>
              </span>
              {busy === school.id ? (
                <span className="text-xs text-muted-foreground">{t.common.loading}</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>

      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
