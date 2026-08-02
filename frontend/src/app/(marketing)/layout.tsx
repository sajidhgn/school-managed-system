import Link from "next/link";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { Button } from "@/components/ui/button";
import { getCurrentUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

/**
 * Public shell: marketing pages, auth forms, invitation acceptance.
 *
 * No authentication required — but it DOES read the session, so a signed-in visitor
 * sees "Go to dashboard" instead of "Sign in". Getting that wrong is a small thing
 * that makes a product feel broken: being asked to log in on a site you are already
 * logged into.
 */
export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  const [user, t] = await Promise.all([getCurrentUser(), getTranslations()]);

  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
              E
            </span>
            {t.common.appName}
          </Link>

          <nav className="hidden items-center gap-1 text-sm sm:flex">
            <Link
              href="/pricing"
              className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {t.nav.plans}
            </Link>
          </nav>

          {/* `ms-auto` (margin-inline-start), not `ml-auto`: under `dir="rtl"` a
              physical left margin would push the actions to the wrong edge. Every
              directional utility in this codebase is logical for the same reason. */}
          <div className="ms-auto flex items-center gap-2">
            <LocaleSwitcher />
            {user ? (
              <Button asChild size="sm">
                <Link href="/dashboard">{t.nav.dashboard}</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/login">{t.common.signIn}</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href="/signup">{t.common.signUp}</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="flex-1">
        {children}
      </main>

      <footer className="border-t border-border/70 py-8">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 text-sm text-muted-foreground sm:flex-row sm:items-center sm:px-6">
          <p>
            © {new Date().getFullYear()} {t.common.appName}
          </p>
          <div className="flex gap-4 sm:ms-auto">
            <Link href="/pricing" className="hover:text-foreground">
              {t.nav.plans}
            </Link>
            <Link href="/platform/login" className="hover:text-foreground">
              Operator console
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
