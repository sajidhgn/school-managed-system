import type { Locale } from "./config";

/**
 * Translation catalogs.
 *
 * A plain nested object rather than a library, deliberately. At this size, `next-intl`
 * or `react-i18next` would add a provider, a build step, an async loader and a set of
 * hooks to solve a problem that is currently one object lookup. The seam is what
 * matters — every user-facing string goes through `t()` — and swapping the
 * implementation later touches this file and nothing else.
 *
 * The English catalog is the source of truth; `Messages` is derived from it, so a key
 * missing from `ur` is a TYPE ERROR rather than a string that silently renders in the
 * wrong language.
 */

const en = {
  common: {
    appName: "EduCloud",
    save: "Save",
    cancel: "Cancel",
    delete: "Delete",
    edit: "Edit",
    create: "Create",
    search: "Search",
    loading: "Loading…",
    signIn: "Sign in",
    signOut: "Sign out",
    signUp: "Get started",
    back: "Back",
    next: "Next",
    none: "None",
    required: "Required",
    optional: "Optional",
    unlimited: "Unlimited",
    perMonth: "/mo",
    perYear: "/yr",
  },
  nav: {
    dashboard: "Dashboard",
    schools: "Schools",
    students: "Students",
    classes: "Classes",
    people: "People & access",
    members: "Members",
    roles: "Roles",
    invitations: "Invitations",
    billing: "Billing",
    settings: "Settings",
    audit: "Audit log",
    organizations: "Organizations",
    plans: "Plans",
    metrics: "Metrics",
  },
  marketing: {
    heroTitle: "School management that scales with your group",
    heroSubtitle:
      "Run every campus from one place. Students, staff, roles and billing — with the data separation a school actually needs.",
    heroCta: "Start free",
    heroSecondary: "See pricing",
    pricingTitle: "Simple, predictable pricing",
    pricingSubtitle: "Start free. Upgrade when you add your second campus.",
    monthly: "Monthly",
    yearly: "Yearly",
    yearlyHint: "2 months free",
    choosePlan: "Choose plan",
    currentPlan: "Current plan",
    contactSales: "Contact sales",
  },
  auth: {
    loginTitle: "Sign in",
    loginSubtitle: "Welcome back.",
    signupTitle: "Create your organization",
    signupSubtitle: "Free to start. No card required.",
    email: "Email address",
    password: "Password",
    fullName: "Full name",
    organizationName: "Organization name",
    country: "Country",
    forgotPassword: "Forgot your password?",
    noAccount: "Don't have an account?",
    haveAccount: "Already have an account?",
    selectContext: "Choose where to sign in",
    selectContextHint: "You belong to more than one school. Pick one to continue.",
    checkEmail: "Check your email",
    verifyEmailSent:
      "We sent you a verification link. Follow it to finish setting up your account.",
    resetSent: "If an account exists for that address, we have sent a reset link.",
  },
  invite: {
    title: "You have been invited",
    joinAs: "You are joining as",
    acceptCta: "Accept invitation",
    createAccount: "Create your account",
    signInToAccept: "Sign in to accept",
    expired: "This invitation is no longer valid.",
    expiredHint: "Ask whoever invited you to send a new one.",
  },
  onboarding: {
    title: "Create your first school",
    subtitle:
      "You can add more campuses later. You'll be set up as principal of this one.",
    schoolName: "School name",
    schoolCode: "Short code",
    schoolCodeHint: "Appears on ID cards and reports, e.g. MAIN",
    city: "City",
    create: "Create school",
  },
  billing: {
    plan: "Plan",
    usage: "Usage",
    invoices: "Invoices",
    changePlan: "Change plan",
    cancelPlan: "Cancel subscription",
    cancelAtPeriodEnd: "Your subscription ends at the close of the current period.",
    overLimitTitle: "You are over your plan's limits",
    overLimitBody:
      "Your existing records stay available. New ones are paused until you are back under the cap or upgrade.",
    pastDueTitle: "We could not process your last payment",
    pastDueBody: "Update your payment details to avoid interruption.",
    suspendedTitle: "This organization is read-only",
    suspendedBody: "You can still view and export everything. Contact support to restore access.",
  },
  errors: {
    generic: "Something went wrong. Please try again.",
    notFound: "Not found",
    forbidden: "You do not have permission to do that.",
    sessionExpired: "Your session has expired. Please sign in again.",
  },
} as const;

/**
 * The catalog shape. Derived from `en`, so every locale must supply every key —
 * a missing translation is a compile error, not a string that renders in English
 * for one user and Urdu for the next.
 */
export type Messages = {
  [K in keyof typeof en]: Record<keyof (typeof en)[K], string>;
};

/**
 * Urdu.
 *
 * INCOMPLETE ON PURPOSE, and structurally so: the type above forces every key to
 * exist, and the ones not yet professionally translated hold their English text. A
 * partially translated app that renders is far more useful than one blocked on a
 * complete translation pass — and the type system means adding a key to `en` fails
 * the build here until someone decides what it says.
 */
const ur: Messages = {
  common: {
    appName: "ایجوکلاؤڈ",
    save: "محفوظ کریں",
    cancel: "منسوخ کریں",
    delete: "حذف کریں",
    edit: "ترمیم کریں",
    create: "بنائیں",
    search: "تلاش کریں",
    loading: "لوڈ ہو رہا ہے…",
    signIn: "سائن ان",
    signOut: "سائن آؤٹ",
    signUp: "شروع کریں",
    back: "واپس",
    next: "اگلا",
    none: "کوئی نہیں",
    required: "لازمی",
    optional: "اختیاری",
    unlimited: "لامحدود",
    perMonth: "/ماہ",
    perYear: "/سال",
  },
  nav: {
    dashboard: "ڈیش بورڈ",
    schools: "اسکول",
    students: "طلبہ",
    classes: "جماعتیں",
    people: "عملہ اور رسائی",
    members: "اراکین",
    roles: "کردار",
    invitations: "دعوت نامے",
    billing: "بلنگ",
    settings: "ترتیبات",
    audit: "آڈٹ لاگ",
    organizations: "ادارے",
    plans: "منصوبے",
    metrics: "اعداد و شمار",
  },
  marketing: {
    heroTitle: "School management that scales with your group",
    heroSubtitle:
      "Run every campus from one place. Students, staff, roles and billing — with the data separation a school actually needs.",
    heroCta: "مفت شروع کریں",
    heroSecondary: "قیمتیں دیکھیں",
    pricingTitle: "سادہ، قابلِ پیش گوئی قیمتیں",
    pricingSubtitle: "مفت شروع کریں۔ دوسرا کیمپس شامل کرتے وقت اپ گریڈ کریں۔",
    monthly: "ماہانہ",
    yearly: "سالانہ",
    yearlyHint: "2 ماہ مفت",
    choosePlan: "منصوبہ منتخب کریں",
    currentPlan: "موجودہ منصوبہ",
    contactSales: "رابطہ کریں",
  },
  auth: {
    loginTitle: "سائن ان",
    loginSubtitle: "خوش آمدید۔",
    signupTitle: "اپنا ادارہ بنائیں",
    signupSubtitle: "مفت شروع کریں۔ کارڈ کی ضرورت نہیں۔",
    email: "ای میل ایڈریس",
    password: "پاس ورڈ",
    fullName: "پورا نام",
    organizationName: "ادارے کا نام",
    country: "ملک",
    forgotPassword: "پاس ورڈ بھول گئے؟",
    noAccount: "اکاؤنٹ نہیں ہے؟",
    haveAccount: "پہلے سے اکاؤنٹ ہے؟",
    selectContext: "سائن ان کرنے کی جگہ منتخب کریں",
    selectContextHint: "آپ ایک سے زیادہ اسکول سے وابستہ ہیں۔ جاری رکھنے کے لیے ایک منتخب کریں۔",
    checkEmail: "اپنی ای میل دیکھیں",
    verifyEmailSent: "ہم نے آپ کو تصدیقی لنک بھیجا ہے۔ اکاؤنٹ مکمل کرنے کے لیے اس پر جائیں۔",
    resetSent: "اگر اس پتے کا اکاؤنٹ موجود ہے تو ہم نے ری سیٹ لنک بھیج دیا ہے۔",
  },
  invite: {
    title: "آپ کو مدعو کیا گیا ہے",
    joinAs: "آپ شامل ہو رہے ہیں بطور",
    acceptCta: "دعوت قبول کریں",
    createAccount: "اپنا اکاؤنٹ بنائیں",
    signInToAccept: "قبول کرنے کے لیے سائن ان کریں",
    expired: "یہ دعوت اب کارآمد نہیں رہی۔",
    expiredHint: "جس نے آپ کو مدعو کیا تھا، ان سے نیا لنک طلب کریں۔",
  },
  onboarding: {
    title: "اپنا پہلا اسکول بنائیں",
    subtitle: "آپ بعد میں مزید کیمپس شامل کر سکتے ہیں۔ آپ اس کے پرنسپل ہوں گے۔",
    schoolName: "اسکول کا نام",
    schoolCode: "مختصر کوڈ",
    schoolCodeHint: "شناختی کارڈ اور رپورٹس پر ظاہر ہوتا ہے، مثلاً MAIN",
    city: "شہر",
    create: "اسکول بنائیں",
  },
  billing: {
    plan: "منصوبہ",
    usage: "استعمال",
    invoices: "رسیدیں",
    changePlan: "منصوبہ تبدیل کریں",
    cancelPlan: "سبسکرپشن منسوخ کریں",
    cancelAtPeriodEnd: "آپ کی سبسکرپشن موجودہ مدت کے اختتام پر ختم ہو جائے گی۔",
    overLimitTitle: "آپ اپنے منصوبے کی حد سے تجاوز کر چکے ہیں",
    overLimitBody:
      "آپ کا موجودہ ریکارڈ دستیاب رہے گا۔ نئے اندراجات اپ گریڈ تک روک دیے گئے ہیں۔",
    pastDueTitle: "ہم آپ کی آخری ادائیگی پر کارروائی نہیں کر سکے",
    pastDueBody: "تعطل سے بچنے کے لیے ادائیگی کی تفصیلات اپ ڈیٹ کریں۔",
    suspendedTitle: "یہ ادارہ صرف پڑھنے کے لیے ہے",
    suspendedBody: "آپ اب بھی سب کچھ دیکھ اور برآمد کر سکتے ہیں۔ رسائی بحال کرنے کے لیے رابطہ کریں۔",
  },
  errors: {
    generic: "کچھ غلط ہو گیا۔ دوبارہ کوشش کریں۔",
    notFound: "نہیں ملا",
    forbidden: "آپ کے پاس یہ کرنے کی اجازت نہیں ہے۔",
    sessionExpired: "آپ کا سیشن ختم ہو گیا ہے۔ دوبارہ سائن ان کریں۔",
  },
};

const CATALOGS: Record<Locale, Messages> = {
  en: en as unknown as Messages,
  ur,
};

export function getMessages(locale: Locale): Messages {
  return CATALOGS[locale];
}

export type { Locale };
