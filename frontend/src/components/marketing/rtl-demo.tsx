"use client";

import { CalendarCheck, FileText, MessageCircle, Receipt, Search, Users } from "lucide-react";
import { useState } from "react";
import { flushSync } from "react-dom";

import { LogoMark } from "@/components/marketing/logo";
import type { Locale } from "@/lib/i18n/config";
import { cn } from "@/lib/utils";

/**
 * A miniature of the admin panel that flips between English and Urdu. The Urdu
 * strings are the app's own (lib/i18n/messages.ts), so this shows what a school
 * actually gets.
 *
 * It starts in the page's own language and changes only when the visitor asks:
 * an English page shows no Urdu until someone presses "Urdu". Where the browser
 * supports view transitions, the sidebar and content slide to their mirrored
 * places instead of jumping.
 */

type Lang = "en" | "ur";

const COPY = {
  en: {
    app: "SchoolYar",
    search: "Search",
    nav: ["Students", "Attendance", "Fees", "Test papers", "WhatsApp"],
    title: "Fees",
    rows: [
      ["Ayesha Khan", "Paid"],
      ["Bilal Ahmed", "Due"],
      ["Fatima Zahra", "Paid"],
    ],
    save: "Save",
  },
  ur: {
    app: "اسکول یار",
    search: "تلاش کریں",
    nav: ["طلبہ", "حاضری", "فیس", "ٹیسٹ پیپرز", "واٹس ایپ"],
    title: "فیس",
    rows: [
      ["عائشہ خان", "ادا شدہ"],
      ["بلال احمد", "واجب الادا"],
      ["فاطمہ زہرا", "ادا شدہ"],
    ],
    save: "محفوظ کریں",
  },
} as const;

const NAV_ICONS = [Users, CalendarCheck, Receipt, FileText, MessageCircle];

/** The toggle's own labels, in the page's language. */
const TOGGLE: Record<Locale, { group: string; en: string; ur: string }> = {
  en: { group: "Language of the example", en: "English", ur: "Urdu" },
  ur: { group: "مثال کی زبان", en: "انگریزی", ur: "اردو" },
};

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => unknown;
};

function switchTo(next: Lang, setLang: (lang: Lang) => void) {
  const doc = document as ViewTransitionDocument;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (doc.startViewTransition && !still) {
    doc.startViewTransition(() => flushSync(() => setLang(next)));
  } else {
    setLang(next);
  }
}

export function RtlDemo({ locale }: { locale: Locale }) {
  const [lang, setLang] = useState<Lang>(locale);
  const toggle = TOGGLE[locale];

  const copy = COPY[lang];
  const urdu = lang === "ur";

  return (
    <div>
      <div
        role="group"
        aria-label={toggle.group}
        className="mb-5 inline-flex rounded-full border border-mk-line bg-mk-card p-1"
      >
        {(["en", "ur"] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={lang === option}
            onClick={() => {
              if (option !== lang) switchTo(option, setLang);
            }}
            className={cn(
              "h-9 rounded-full px-4 text-sm font-bold transition-colors",
              lang === option ? "bg-mk-ink text-mk-ink-fg" : "text-mk-muted hover:text-mk-text",
            )}
          >
            {toggle[option]}
          </button>
        ))}
      </div>

      <div
        dir={urdu ? "rtl" : "ltr"}
        lang={lang}
        aria-hidden
        className={cn(
          "mk-rtl-card overflow-hidden rounded-2xl border border-mk-line bg-mk-card shadow-[0_30px_60px_-36px_rgb(15_20_45/0.5)]",
          urdu ? "font-mk-urdu text-sm leading-[1.8]" : "text-sm",
        )}
      >
        <div className="flex h-14 items-center gap-3 border-b border-mk-line px-4">
          <LogoMark className="size-6" />
          <b className={urdu ? "" : "font-mk-display text-base"}>{copy.app}</b>
          <span className="ms-auto flex h-8 w-36 items-center gap-2 rounded-lg border border-mk-line px-2.5 text-mk-muted">
            <Search className="size-3.5 shrink-0" />
            {copy.search}
          </span>
        </div>
        <div className="flex">
          <nav className="mk-rtl-side w-[38%] max-w-44 shrink-0 border-e border-mk-line p-2.5">
            {copy.nav.map((item, i) => {
              const Icon = NAV_ICONS[i]!;
              return (
                <span
                  key={i}
                  className={cn(
                    "flex h-9 items-center gap-2.5 rounded-lg px-2.5",
                    i === 2 ? "bg-mk-ink-soft font-bold text-mk-ink" : "text-mk-muted",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  <span className="truncate">{item}</span>
                </span>
              );
            })}
          </nav>
          <div className="mk-rtl-main min-w-0 flex-1 p-4">
            <p className={cn("flex h-9 items-center font-bold", urdu ? "text-lg" : "font-mk-display text-xl")}>
              {copy.title}
            </p>
            {copy.rows.map(([name, status], i) => (
              <div key={i} className="flex h-10 items-center justify-between gap-2 border-b border-mk-line">
                <span className="truncate">{name}</span>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 text-xs font-bold",
                    i === 1 ? "bg-mk-text text-mk-paper" : "bg-mk-ink-soft text-mk-ink",
                  )}
                >
                  {status}
                </span>
              </div>
            ))}
            <div className="mt-4 flex">
              <span className="mk-rtl-btn ms-auto inline-flex h-9 items-center rounded-lg bg-mk-ink px-4 font-bold text-mk-ink-fg">
                {copy.save}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
