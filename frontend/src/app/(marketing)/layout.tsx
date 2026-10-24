import { buttonVariants } from "@heroui/styles";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { getCopy } from "@/components/marketing/copy";
import { HeroUIScope, OVERLAY_ROOT_ID } from "@/components/marketing/heroui-scope";
import { LocaleMenu } from "@/components/marketing/locale-menu";
import { LocaleToggle } from "@/components/marketing/locale-toggle";
import { LogoMark } from "@/components/marketing/logo";
import { MobileMenu } from "@/components/marketing/mobile-menu";
import { navEntries } from "@/components/marketing/nav/entries";
import { HeaderShell } from "@/components/marketing/nav/header-shell";
import { MegaNav } from "@/components/marketing/nav/mega-nav";
import { SiteFooter } from "@/components/marketing/site-footer";
import { ThemeToggle } from "@/components/marketing/theme-picker";
import { TopBar } from "@/components/marketing/top-bar";
import { WhatsAppButton } from "@/components/marketing/whatsapp-button";
import { getCurrentUser } from "@/lib/auth/session";
import { getLocale } from "@/lib/i18n/server";

import { marketingFontVariables } from "./fonts";
import "./heroui.css";
import "./marketing.css";
import "./site.css";

/**
 * Public shell: marketing pages, auth forms, invitation acceptance.
 *
 * No authentication required — but it DOES read the session, so a signed-in visitor
 * sees "Go to dashboard" instead of "Sign in". Getting that wrong is a small thing
 * that makes a product feel broken: being asked to log in on a site you are already
 * logged into.
 *
 * `.mk` scopes the public site's palette and faces (marketing.css, site.css,
 * fonts.ts), so none of it leaks into the tenant panel. Above the sticky header is
 * a thin announcement bar that scrolls away; the header carries the mega menus
 * (nav/mega-nav.tsx) from `lg` and a drawer below it. Both read the same entries
 * (nav/entries.ts).
 *
 * Controls are HeroUI. Its theme is scoped to `.mk-heroui` (heroui.css), which
 * the header, footer, marketing pages and overlay root carry and the auth forms,
 * built from the panel's own components, do not.
 */
export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  const [user, locale] = await Promise.all([getCurrentUser(), getLocale()]);
  const copy = getCopy(locale);
  const entries = navEntries(locale);

  return (
    <div className={`mk ${marketingFontVariables} flex min-h-svh flex-col`}>
      <HeroUIScope>
        <TopBar locale={locale} />
        <HeaderShell>
          <div className="mk-container flex h-16 items-center gap-3 sm:gap-6">
            <Link href="/" className="mk-brand">
              <LogoMark />
              {/* Below 375px the name gives way so the theme and menu buttons still
                  fit; the logo keeps it as its accessible name. */}
              <span className="max-[374px]:sr-only">{locale === "ur" ? "اسکول یار" : "SchoolYar"}</span>
            </Link>

            <MegaNav entries={entries} label="Site" />

            {/* `ms-auto` (margin-inline-start), not `ml-auto`: under `dir="rtl"` a
                physical left margin would push the actions to the wrong edge. Every
                directional utility in this codebase is logical for the same reason. */}
            <div className="ms-auto flex shrink-0 items-center gap-2">
              {/* The theme button stays on the bar at every width; below `sm` the
                  language picker moves into the menu. */}
              <div className="flex items-center gap-1">
                <div className="hidden sm:flex">
                  <LocaleMenu />
                </div>
                <ThemeToggle />
              </div>
              {user ? (
                <Link href="/dashboard" className={buttonVariants({ variant: "primary", size: "sm" })}>
                  {copy.common.dashboard}
                </Link>
              ) : (
                <>
                  <Link
                    href="/login"
                    className={buttonVariants({
                      variant: "ghost",
                      size: "sm",
                      className: "hidden font-semibold text-mk-muted hover:text-mk-text sm:inline-flex",
                    })}
                  >
                    {copy.common.signIn}
                  </Link>
                  <Link href="/signup" className={buttonVariants({ variant: "primary", size: "sm", className: "mk-shine" })}>
                    {copy.common.getStarted}
                    <ArrowRight className="size-3.5 rtl:-scale-x-100 max-sm:hidden" aria-hidden />
                  </Link>
                </>
              )}
              <MobileMenu
                label={copy.common.menu}
                entries={entries}
                actions={
                  user ? null : (
                    <>
                      <Link href="/signup" className={buttonVariants({ variant: "primary", fullWidth: true })}>
                        {copy.common.startFree}
                      </Link>
                      <Link href="/login" className={buttonVariants({ variant: "outline", fullWidth: true })}>
                        {copy.common.signIn}
                      </Link>
                    </>
                  )
                }
              >
                <LocaleToggle />
              </MobileMenu>
            </div>
          </div>
        </HeaderShell>

        <main id="main" className="flex-1">
          {children}
        </main>

        <SiteFooter locale={locale} signedIn={Boolean(user)} />
        <WhatsAppButton common={copy.common} />
        <div id={OVERLAY_ROOT_ID} className="mk-heroui" />
      </HeroUIScope>
    </div>
  );
}
