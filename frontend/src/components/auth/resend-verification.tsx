"use client";

import { MailCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { publicRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";

/** How long the button rests after a send. The API rate-limits too; this just stops
 *  a second click while the first email is still in flight to the inbox. */
const COOLDOWN_SECONDS = 60;

/**
 * "Didn't get the email?" — send the verification link again.
 *
 * =============================================================================
 * ONE ANSWER FOR EVERY ADDRESS
 * =============================================================================
 *   The API answers the same way whether the address is registered, unregistered,
 *   or already verified, so this cannot be used to find out which emails have an
 *   account. The screen keeps that promise: a transport error and a success both
 *   land on the same sentence. The only failure shown is a rate limit (429), which
 *   says nothing about the address.
 *
 * Pass `email` when the caller already knows it (signup, a failed login). Without
 * it, the component asks for one — the expired-link page has no other way to know.
 */
export function ResendVerification({ email }: { email?: string }) {
  const { t } = useTranslations();
  const [address, setAddress] = useState(email ?? "");
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const trimmed = address.trim();
  const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);

  async function send(event?: React.FormEvent) {
    event?.preventDefault();
    if (!valid || pending || cooldown > 0) return;
    setPending(true);
    setError(null);
    try {
      await publicRequest("/resend-verification", { email: trimmed });
      setSent(true);
      setCooldown(COOLDOWN_SECONDS);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError(err.message);
      } else {
        // Same sentence as success — see the note above.
        setSent(true);
        setCooldown(COOLDOWN_SECONDS);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={send} className="grid gap-2 text-start" noValidate>
      {email === undefined ? (
        <Input
          type="email"
          autoComplete="email"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder={t.auth.email}
          aria-label={t.auth.email}
        />
      ) : null}

      <Button
        type="submit"
        variant="outline"
        loading={pending}
        disabled={!valid || cooldown > 0}
      >
        {t.auth.resendVerification}
      </Button>

      {sent ? (
        <p role="status" className="flex items-start gap-2 text-xs text-muted-foreground">
          <MailCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
          <span>
            {t.auth.resendVerificationSent}
            {cooldown > 0 ? (
              <span className="block">{fill(t.auth.resendIn, { seconds: cooldown })}</span>
            ) : null}
          </span>
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
