import type { Locale } from "@/lib/i18n/config";

import { en } from "./copy-en";
import { ur } from "./copy-ur";

/**
 * Every word on the public site, in English and Urdu.
 *
 * The app's own catalog (lib/i18n/messages.ts) holds the panel's chrome; the
 * marketing copy is long-form and changes on a different rhythm, so it lives here.
 * `MarketingCopy` is the contract both languages implement, so a sentence added
 * in English without its Urdu is a type error, not a gap on the page.
 *
 * Every claim must be true of the shipped product; the sources are the module
 * specs in docs/modules/. Where a school will ask about something we do not do
 * yet (online payment, absence alerts), the FAQ says "not yet" plainly.
 */

export type FeatureSlug =
  | "whatsapp-diary"
  | "whatsapp-attendance"
  | "fee-management"
  | "test-paper-generator"
  | "attendance"
  | "multi-campus"
  | "urdu";

/** A heading and its sentence: a fact, a step, or a question and its answer. */
export type Pair = readonly [title: string, body: string];

/** One AI workflow on the home page: its name, what staff send, what comes back. */
export type AiFlow = readonly [title: string, send: string, result: string];

/** A link in a header menu: its name and the line under it. */
export type NavText = { label: string; body: string };

/** One kind of person who uses SchoolYar, on the home page's roles band. */
export type RoleCopy = { title: string; body: string; points: string[] };

export type FeatureCopy = {
  /** Short label for navigation, footer and cards. */
  nav: string;
  /** The <title>; the root layout appends " · SchoolYar". */
  metaTitle: string;
  metaDescription: string;
  eyebrow: string;
  h1: string;
  lede: string;
  /** One sentence for cards on /features and "see also". */
  summary: string;
  /** A real sequence, so it is numbered. Omitted where there is none. */
  steps?: Pair[];
  detailsTitle: string;
  details: Pair[];
  faqs: Pair[];
};

export type MarketingCopy = {
  common: {
    home: string;
    features: string;
    allFeatures: string;
    readMore: string;
    howItWorks: string;
    detailsLabel: string;
    questionsTitle: string;
    questionsLede: { before: string; link: string; after: string };
    moreIn: string;
    alsoIncluded: string;
    startFree: string;
    seePricing: string;
    freeNote: string;
    signIn: string;
    getStarted: string;
    dashboard: string;
    pricing: string;
    operatorConsole: string;
    menu: string;
    tagline: string;
    /** The second call to action when a contact is set (see `demoUrl`). */
    bookDemo: string;
    /** Typed into the WhatsApp chat (or the email subject) "Book a free demo" opens. */
    demoMessage: string;
    /** The floating WhatsApp button's label. */
    talkOnWhatsApp: string;
    /** Typed into the chat the floating button opens. */
    contactMessage: string;
  };
  /** The header's menus and the announcement bar above them. */
  nav: {
    product: string;
    support: string;
    platformGroup: string;
    whyGroup: string;
    overview: NavText;
    tour: NavText;
    ai: NavText;
    why: NavText;
    security: NavText;
    roles: NavText;
    /** The Product menu's featured card. */
    start: NavText;
    aiGroup: string;
    officeGroup: string;
    /** Under the Features menu: what has no page of its own. */
    alsoLine: string;
    faq: NavText;
    pricingFaq: NavText;
    demo: NavText;
    whatsapp: NavText;
    email: NavText;
    phone: NavText;
    signIn: NavText;
    announcement: { tag: string; text: string };
  };
  /** Footer column headings and the one link no other place names. */
  footer: {
    /** The brand column's sentence. */
    about: string;
    support: string;
    rights: string;
    product: string;
    account: string;
    language: string;
    forgotPassword: string;
    contact: string;
    whatsapp: string;
    email: string;
    phone: string;
  };
  home: {
    metaDescription: string;
    hero: { title: { before: string; em: string; after: string }; lede: string; points: string[] };
    /** The hero's illustrated dashboard. Its figures are an example, and say so. */
    dashboard: {
      description: string;
      nav: string[];
      greeting: string;
      campus: string;
      search: string;
      kpis: (readonly [label: string, value: string, note: string])[];
      chartTitle: string;
      chartNote: string;
      months: string[];
      todayTitle: string;
      legend: [present: string, absent: string, late: string];
      activityTitle: string;
      activity: (readonly [title: string, time: string])[];
      callouts: Pair[];
    };
    /** The label over the band of subjects under the hero. */
    ticker: string;
    platform: { title: string; lede: string; more: string };
    tour: { title: string; lede: string };
    /** `hub` names the modules drawn around SchoolYar in the diagram. */
    security: { title: string; lede: string; points: Pair[]; hub: string[] };
    roles: { title: string; lede: string; items: RoleCopy[] };
    /** Facts about the product, not about customers: there are none to cite yet. */
    numbers: { title: string; items: (readonly [value: number, label: string])[] };
    why: { title: string; lede: string; items: Pair[] };
    /** The diary demo, used on the home page's tour and the diary's own page. */
    steps: [string, string, string, string];
    pause: string;
    play: string;
    demoDescription: string;
    fees: { title: string; lede: string; facts: Pair[]; more: string };
    papers: {
      title: string;
      lede: string;
      recipeLede: string;
      recipe: string[];
      draft: string;
      more: string;
    };
    attendance: { title: string; lede: string; facts: Pair[]; more: string };
    campuses: { title: string; lede: string; pillars: Pair[]; more: string };
    urdu: { title: string; lede: string; more: string };
    yaar: { title: string; body: string };
    /** The AI workflows, in the order of `AI_FLOW_SLUGS` on the home page. */
    ai: { title: string; lede: string; send: string; result: string; flows: AiFlow[] };
    start: { title: string; steps: Pair[] };
    faqs: Pair[];
    cta: { title: string; body: string };
  };
  featuresIndex: { metaTitle: string; metaDescription: string; title: string; lede: string };
  pricing: {
    metaDescription: string;
    unavailable: string;
    /** Shown only when a contact is set; `link` opens it. */
    groups: { before: string; link: string; after: string };
    faqs: Pair[];
  };
  /** The panel beside the sign-in and sign-up forms. */
  authAside: { title: string; body: string; points: string[] };
  /** Smaller capabilities, in the order of ALSO_INCLUDED_ICONS. */
  alsoIncluded: string[];
  /** What each illustrated demo shows, for screen readers (the demos are aria-hidden). */
  demos: { challan: string; pages: string; register: string; campus: string; attendanceChat: string };
  features: Record<FeatureSlug, FeatureCopy>;
};

const COPY: Record<Locale, MarketingCopy> = { en, ur };

export function getCopy(locale: Locale): MarketingCopy {
  return COPY[locale];
}

/**
 * Short labels and decorative words, in both languages. A page shows only the
 * one for the visitor's language: an English page carries no Urdu and an Urdu
 * page no English.
 */
export const LABELS = {
  audience: { en: "For schools and school groups", ur: "اسکولوں اور اسکول گروپس کے لیے" },
  diary: { en: "WhatsApp diary", ur: "واٹس ایپ ڈائری" },
  fees: { en: "Fees", ur: "فیس" },
  papers: { en: "Test papers", ur: "ٹیسٹ پیپرز" },
  attendance: { en: "Attendance", ur: "حاضری" },
  campuses: { en: "Campuses", ur: "کیمپس" },
  urdu: { en: "Urdu", ur: "اردو" },
  ai: { en: "AI", ur: "اے آئی" },
  begin: { en: "Getting started", ur: "آغاز کیسے کریں" },
  also: { en: "Also included", ur: "یہ بھی شامل" },
  how: { en: "How it works", ur: "طریقۂ کار" },
  details: { en: "Details", ur: "تفصیل" },
  questions: { en: "Questions", ur: "سوالات" },
  related: { en: "See also", ur: "مزید دیکھیں" },
  features: { en: "Features", ur: "خصوصیات" },
  pricing: { en: "Pricing", ur: "قیمتیں" },
  start: { en: "Start", ur: "آغاز" },
  name: { en: "Our name", ur: "ہمارا نام" },
  platform: { en: "Platform", ur: "پلیٹ فارم" },
  tour: { en: "Product tour", ur: "پروڈکٹ ٹور" },
  security: { en: "Security", ur: "تحفظ" },
  roles: { en: "For every role", ur: "ہر کردار کے لیے" },
  numbers: { en: "In numbers", ur: "اعداد میں" },
  why: { en: "Why SchoolYar", ur: "اسکول یار کیوں" },
} as const;

export type BiLabelText = { en: string; ur: string };
