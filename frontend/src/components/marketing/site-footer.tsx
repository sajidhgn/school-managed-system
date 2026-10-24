import { buttonVariants, linkVariants } from "@heroui/styles";
import type { Route } from "next";
import Link from "next/link";
import { ArrowRight, Mail, MessageCircle, Phone } from "lucide-react";

import { getCopy } from "@/components/marketing/copy";
import { featurePath, getFeatures } from "@/components/marketing/features";
import { LocaleToggle } from "@/components/marketing/locale-toggle";
import { LogoMark } from "@/components/marketing/logo";
import { Reveal, Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { ThemeToggle } from "@/components/marketing/theme-picker";
import type { Locale } from "@/lib/i18n/config";
import { CONTACT, whatsappUrl } from "@/lib/site";
import { cn } from "@/lib/utils";

// HeroUI's link, with `py-1` making each one a 30px target for a thumb without
// changing the rhythm of the column.
const LINK = linkVariants().base({ className: "py-1 font-normal text-mk-muted hover:text-mk-text" });

/**
 * The public site's footer: the brand and its sentence, columns of links, the
 * team's contacts when they are set, then the name set huge across the foot.
 *
 * Every public page is linked from here, so each is one click from any other on
 * every screen size; that is also how crawlers find them. Only pages that exist are
 * listed: social icons and legal links wait until there are accounts and pages
 * behind them.
 */
export function SiteFooter({ locale, signedIn }: { locale: Locale; signedIn: boolean }) {
  const { common, footer, nav } = getCopy(locale);
  // The brand name in the visitor's language only.
  const name = locale === "ur" ? "اسکول یار" : "SchoolYar";

  // Only the ways in that are set; the list is left out when none is.
  const whatsapp = whatsappUrl(common.contactMessage);
  const contact = [
    ...(whatsapp ? [{ href: whatsapp, label: footer.whatsapp, icon: MessageCircle, external: true }] : []),
    ...(CONTACT.phone
      ? [{ href: `tel:${CONTACT.phone.replace(/[^\d+]/g, "")}`, label: CONTACT.phone, icon: Phone, external: false }]
      : []),
    ...(CONTACT.email ? [{ href: `mailto:${CONTACT.email}`, label: CONTACT.email, icon: Mail, external: false }] : []),
  ];

  const columns: { title: string; links: { href: Route; label: string }[] }[] = [
    {
      title: common.features,
      links: getFeatures(locale).map((feature) => ({ href: featurePath(feature.slug) as Route, label: feature.nav })),
    },
    {
      title: footer.product,
      links: [
        { href: "/#platform" as Route, label: nav.overview.label },
        { href: "/#tour" as Route, label: nav.tour.label },
        { href: "/#why" as Route, label: nav.why.label },
        { href: "/#security" as Route, label: nav.security.label },
        { href: "/features", label: common.allFeatures },
        { href: "/pricing", label: common.pricing },
      ],
    },
    {
      title: footer.support,
      links: [
        { href: "/#questions" as Route, label: nav.faq.label },
        { href: "/pricing#questions" as Route, label: nav.pricingFaq.label },
        ...(signedIn
          ? [{ href: "/dashboard" as Route, label: common.dashboard }]
          : [
              { href: "/login" as Route, label: common.signIn },
              { href: "/forgot-password" as Route, label: footer.forgotPassword },
            ]),
        { href: "/platform/login", label: common.operatorConsole },
      ],
    },
  ];

  return (
    <footer className="mk-night mk-footer mk-heroui">
      <div className="mk-container pt-16 lg:pt-24">
        <Stagger className="grid gap-x-8 gap-y-12 text-[0.92rem] sm:grid-cols-2 lg:grid-cols-[minmax(0,1.5fr)_repeat(3,minmax(0,1fr))]">
          <StaggerItem className="sm:col-span-2 lg:col-span-1">
            <Link href="/" className="mk-brand">
              <LogoMark />
              {name}
            </Link>
            <p className="mt-5 max-w-sm leading-relaxed text-pretty text-mk-muted">{footer.about}</p>
            {signedIn ? null : (
              <Link href="/signup" className={buttonVariants({ variant: "primary", className: "mk-shine mt-6" })}>
                {common.startFree}
                <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
              </Link>
            )}
            {contact.length > 0 ? (
              <ul className="mt-7 grid gap-2.5">
                {contact.map(({ href, label, icon: Icon, external }) => (
                  <li key={href}>
                    {/* Numbers and addresses read left to right in Urdu too. */}
                    <a
                      href={href}
                      className="inline-flex items-center gap-2.5 text-mk-muted transition-colors hover:text-mk-text"
                      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : { dir: "ltr" })}
                    >
                      <span className="mk-footer__icon">
                        <Icon className="size-3.5" aria-hidden />
                      </span>
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </StaggerItem>

          {columns.map(({ title, links }) => (
            <StaggerItem key={title}>
              <nav aria-label={title}>
                <p className="font-semibold text-mk-text">{title}</p>
                <ul className="mt-4 grid gap-1">
                  {links.map(({ href, label }) => (
                    <li key={href}>
                      <Link href={href} className={LINK}>
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
            </StaggerItem>
          ))}
        </Stagger>

        <div className="mt-16 flex flex-col gap-5 border-t border-mk-line py-7 text-sm text-mk-muted md:flex-row md:items-center md:justify-between">
          <p>
            © {new Date().getFullYear()} {name}. {footer.rights}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <span className="sr-only">{footer.language}</span>
            <LocaleToggle />
            <ThemeToggle />
          </div>
        </div>
      </div>

      <Reveal y={60} className="mk-container overflow-hidden">
        <p className={cn("mk-wordmark", locale === "ur" && "mk-wordmark--ur mk-ur-deco")} lang={locale} aria-hidden>
          {name}
        </p>
      </Reveal>
    </footer>
  );
}
