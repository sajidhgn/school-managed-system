"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { Building2, MessageCircle } from "lucide-react";
import * as React from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, toProblem } from "@/lib/api/errors";
import type {
  GuardianContextSummary,
  GuardianLoginResponse,
  OtpRequestResponse,
} from "@/lib/api/types";

/**
 * Phone → WhatsApp code → (pick a school group) → the portal.
 *
 * Every call goes to a fixed `/api/parent/*` handler, which keeps the tokens in
 * httpOnly cookies. The request-code answer is the same whether or not the number
 * is registered, so this form never says "unknown number" -- it says where the code
 * was sent if the number is known, and what to do if nothing arrives.
 */

type Step =
  | { kind: "phone" }
  | { kind: "code"; masked: string }
  | { kind: "select"; contexts: GuardianContextSummary[] }
  | { kind: "no_access" };

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api/parent/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(await toProblem(response));
  return (await response.json()) as T;
}

/** Seconds left before "send a new code" may be pressed. */
function useCountdown(): [number, (seconds: number) => void] {
  const [left, setLeft] = React.useState(0);
  React.useEffect(() => {
    if (left <= 0) return;
    const id = window.setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => window.clearTimeout(id);
  }, [left]);
  return [left, setLeft];
}

export function ParentLoginForm() {
  const { t } = useTranslations();
  const router = useRouter();
  const [step, setStep] = React.useState<Step>({ kind: "phone" });
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [cooldown, setCooldown] = useCountdown();

  function fail(err: unknown) {
    setError(err instanceof ApiError ? err.message : t.errors.generic);
  }

  function enterPortal() {
    // Push before refresh so the portal renders with the cookie just written.
    router.push("/parent" as Route);
    router.refresh();
  }

  function handle(result: GuardianLoginResponse) {
    if (result.status === "authenticated") return enterPortal();
    if (result.status === "select_required") {
      return setStep({ kind: "select", contexts: result.contexts ?? [] });
    }
    setStep({ kind: "no_access" });
  }

  async function requestCode(event?: React.FormEvent) {
    event?.preventDefault();
    setError(null);
    if (phone.replace(/\D/g, "").length < 10) {
      setError(t.parent.phoneInvalid);
      return;
    }
    setBusy(true);
    try {
      const sent = await post<OtpRequestResponse>("request-code", { phone: phone.trim() });
      setCode("");
      setCooldown(sent.retry_after_seconds);
      setStep({ kind: "code", masked: sent.phone_masked });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function verify(value: string) {
    setError(null);
    if (!/^\d{6}$/.test(value)) {
      setError(t.parent.codeInvalid);
      return;
    }
    setBusy(true);
    try {
      handle(await post<GuardianLoginResponse>("verify", { phone: phone.trim(), code: value }));
    } catch (err) {
      fail(err);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  async function choose(guardianId: string) {
    setError(null);
    setBusy(true);
    try {
      handle(await post<GuardianLoginResponse>("context", { guardian_id: guardianId }));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  if (step.kind === "phone") {
    return (
      <form onSubmit={requestCode} className="grid gap-4" noValidate>
        <Field label={t.parent.phoneLabel} htmlFor="parent_phone">
          <Input
            type="tel"
            inputMode="tel"
            dir="ltr"
            autoComplete="tel"
            autoFocus
            placeholder={t.parent.phonePlaceholder}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </Field>
        <FormError message={error} />
        <Button type="submit" size="lg" loading={busy}>
          <MessageCircle />
          {busy ? t.parent.sendingCode : t.parent.sendCode}
        </Button>
      </form>
    );
  }

  if (step.kind === "code") {
    // Split rather than replaced, so the number sits where each language puts it and
    // stays left-to-right inside an Urdu sentence.
    const [sentBefore, sentAfter = ""] = t.parent.codeSentTo.split("{phone}");
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void verify(code);
        }}
        className="grid gap-4"
        noValidate
      >
        <div className="rounded-lg bg-muted/60 p-3 text-sm">
          <p className="font-medium">
            {sentBefore}
            <bdi dir="ltr" className="tabular-nums">
              {step.masked}
            </bdi>
            {sentAfter}
          </p>
          <p className="mt-1 text-muted-foreground">{t.parent.codeSentHint}</p>
        </div>

        <Field label={t.parent.codeLabel} htmlFor="parent_code">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            dir="ltr"
            maxLength={6}
            placeholder="123456"
            className="text-center font-mono text-lg tracking-[0.5em]"
            value={code}
            onChange={(e) => {
              const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
              setCode(digits);
              // A pasted or autofilled code signs in without another tap.
              if (digits.length === 6 && !busy) void verify(digits);
            }}
          />
        </Field>

        <FormError message={error} />

        <Button type="submit" size="lg" loading={busy}>
          {busy ? t.parent.verifying : t.parent.verify}
        </Button>

        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground hover:underline"
            onClick={() => {
              setError(null);
              setStep({ kind: "phone" });
            }}
          >
            {t.parent.changeNumber}
          </button>
          <button
            type="button"
            disabled={cooldown > 0 || busy}
            className="font-medium text-primary hover:underline disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
            onClick={() => void requestCode()}
          >
            {cooldown > 0
              ? t.parent.resendIn.replace("{seconds}", String(cooldown))
              : t.parent.resend}
          </button>
        </div>
      </form>
    );
  }

  if (step.kind === "select") {
    return (
      <div className="grid gap-4">
        <div>
          <h2 className="font-medium">{t.parent.chooseSchool}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t.parent.chooseSchoolHint}</p>
        </div>
        <ul className="grid gap-2">
          {step.contexts.map((context) => (
            <li key={context.guardian_id}>
              <button
                type="button"
                disabled={busy}
                onClick={() => void choose(context.guardian_id)}
                className="flex w-full items-center gap-3 rounded-lg border border-border bg-card p-3 text-start transition-colors hover:border-primary hover:bg-accent disabled:opacity-60"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-md bg-accent text-accent-foreground">
                  <Building2 className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {context.organization_name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {[
                      context.schools.join(", "),
                      t.parent.childrenCount.replace("{count}", String(context.student_count)),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <FormError message={error} />
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-border p-4">
        <h2 className="font-medium">{t.parent.noAccessTitle}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t.parent.noAccessBody}</p>
      </div>
      <Button
        variant="outline"
        onClick={() => {
          setCode("");
          setStep({ kind: "phone" });
        }}
      >
        {t.parent.changeNumber}
      </Button>
    </div>
  );
}
