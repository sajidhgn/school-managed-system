import type { Metadata } from "next";
import Link from "next/link";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoMark } from "@/components/marketing/logo";
import { getTranslations } from "@/lib/i18n/server";

import { ParentLoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Parent sign-in: a phone number, then a code that arrives on WhatsApp.
 *
 * Laid out for a phone first, because that is where a parent opens the link the
 * school sends them. No password and no "create account": the school registers the
 * number, and the code proves the parent holds it.
 */
export default async function ParentLoginPage() {
  const t = await getTranslations();

  return (
    <main id="main" className="grid min-h-svh place-items-center bg-muted/40 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <LogoMark className="size-8" />
            <span className="font-semibold">{t.parent.portalName}</span>
          </div>
          <LocaleSwitcher />
        </div>

        <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{t.parent.loginTitle}</h1>
          <p className="mt-1.5 text-sm text-muted-foreground text-pretty">
            {t.parent.loginSubtitle}
          </p>
          <div className="mt-6">
            <ParentLoginForm />
          </div>
        </div>

        <p className="mt-5 text-center text-sm text-muted-foreground">
          <Link href="/login" className="hover:text-foreground hover:underline">
            {t.parent.staffLink}
          </Link>
        </p>
      </div>
    </main>
  );
}
