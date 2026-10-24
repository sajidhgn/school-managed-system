import Link from "next/link";
import { ArrowRight, Mail, Phone } from "lucide-react";

import { getCopy } from "@/components/marketing/copy";
import { featurePath } from "@/components/marketing/features";
import type { Locale } from "@/lib/i18n/config";
import { CONTACT } from "@/lib/site";

/**
 * The thin bar above the header: what is new on the start side, and the team's
 * phone and email on the end side when they are set (else the free plan). It
 * scrolls away; only the header below it sticks.
 */
export function TopBar({ locale }: { locale: Locale }) {
  const { nav, common } = getCopy(locale);
  const contacts = [
    ...(CONTACT.phone
      ? [{ href: `tel:${CONTACT.phone.replace(/[^\d+]/g, "")}`, label: CONTACT.phone, icon: Phone }]
      : []),
    ...(CONTACT.email ? [{ href: `mailto:${CONTACT.email}`, label: CONTACT.email, icon: Mail }] : []),
  ];

  return (
    <div className="mk-night mk-topbar">
      <div className="mk-container flex h-10 items-center justify-between gap-4 text-[0.8rem]">
        <Link href={featurePath("test-paper-generator")} className="mk-topbar__news">
          <span className="mk-topbar__tag">{nav.announcement.tag}</span>
          <span className="truncate">{nav.announcement.text}</span>
          <ArrowRight className="size-3.5 shrink-0 rtl:-scale-x-100" aria-hidden />
        </Link>
        <div className="hidden shrink-0 items-center gap-5 text-mk-muted md:flex">
          {contacts.length > 0 ? (
            contacts.map(({ href, label, icon: Icon }) => (
              <a key={href} href={href} className="inline-flex items-center gap-1.5 hover:text-mk-text" dir="ltr">
                <Icon className="size-3.5" aria-hidden />
                {label}
              </a>
            ))
          ) : (
            <span>{common.freeNote}</span>
          )}
        </div>
      </div>
    </div>
  );
}
