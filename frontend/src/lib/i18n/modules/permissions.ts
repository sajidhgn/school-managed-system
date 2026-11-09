"use client";

import { useTranslations } from "@/components/providers/i18n-provider";

/**
 * Urdu for text the BACKEND owns: the permission catalog (`rbac/catalog.py`) and the
 * names of the seeded system roles (`SYSTEM_ROLE_META`).
 *
 * Unlike the other catalogs this one has no English half: English is whatever the API
 * sends, so the two cannot drift. Urdu is looked up by stable code, and anything not
 * listed here (a permission added later, a custom role a school named itself) falls
 * back to the API's text rather than rendering blank.
 */

const PERMISSION_UR: Record<string, string> = {
  "attendance:amend": "جمع شدہ حاضری رجسٹر دوبارہ کھولنا اور درست کرنا۔",
  "attendance:mark": "حاضری لگانا۔",
  "attendance:read": "حاضری کا ریکارڈ دیکھنا۔",
  "audit:read": "آڈٹ لاگ دیکھنا۔",
  "billing:manage": "پلان بدلنا، ادائیگی کی تفصیل اپ ڈیٹ کرنا، منسوخ کرنا۔",
  "billing:read": "سبسکرپشن اور موجودہ پلان دیکھنا۔",
  "book:manage": "لائبریری کی کسی بھی کتاب میں تبدیلی یا اسے حذف کرنا۔",
  "book:read": "نصابی کتابوں کی لائبریری دیکھنا اور کتابوں میں تلاش کرنا۔",
  "book:write": "کتابیں اپ لوڈ کرنا اور اپنی اپ لوڈ کی ہوئی کتابیں سنبھالنا۔",
  "calendar:manage": "تعلیمی سال اور ٹرمز طے کرنا۔",
  "calendar:read": "تعلیمی سال اور ٹرمز دیکھنا۔",
  "class:create": "کلاسیں اور سیکشن بنانا۔",
  "class:delete": "کلاسیں اور سیکشن حذف کرنا۔",
  "class:read": "کلاسیں اور سیکشن دیکھنا۔",
  "class:update": "کلاسوں اور سیکشنز میں ترمیم کرنا۔",
  "class:view_all": "ہر کلاس، سیکشن اور طالب علم دیکھنا — صرف اپنے سپرد کیے گئے نہیں۔",
  "fee:collect": "فیس کی ادائیگی درج کرنا اور رسید جاری کرنا۔",
  "fee:issue": "فیس کے چالان بنانا اور جاری کرنا۔",
  "fee:manage": "فیس کی مدیں اور فیس اسٹرکچر طے کرنا۔",
  "fee:read": "فیس کی مدیں، اسٹرکچر، چالان اور ادائیگیاں دیکھنا۔",
  "fee:void": "فیس کا چالان منسوخ کرنا یا درج شدہ ادائیگی واپس کرنا۔",
  "grade:manage": "نمبر درج کرنا اور ان میں ترمیم کرنا۔",
  "grade:read": "نمبر دیکھنا۔",
  "guardian:create": "سرپرستوں کا اندراج کرنا۔",
  "guardian:delete": "سرپرست کا ریکارڈ ہٹانا۔",
  "guardian:portal": "سرپرست کا سائن اِن نمبر یا پورٹل تک رسائی بدلنا۔",
  "guardian:read": "سرپرست اور ان سے منسلک طلبہ دیکھنا۔",
  "guardian:update": "سرپرستوں اور طلبہ سے ان کے تعلق میں ترمیم کرنا۔",
  "invitation:read": "زیرِ التوا دعوت نامے دیکھنا۔",
  "invitation:resend": "دعوت نامے کی ای میل دوبارہ بھیجنا۔",
  "invitation:revoke": "زیرِ التوا دعوت نامہ منسوخ کرنا۔",
  "invoice:download": "انوائس کی PDF ڈاؤن لوڈ کرنا۔",
  "invoice:read": "انوائسز دیکھنا۔",
  "member:invite": "عملے کے نئے ارکان کو مدعو کرنا۔",
  "member:read": "عملے کے ارکان دیکھنا۔",
  "member:remove": "رکن کو ہٹانا۔",
  "member:reset_password": "رکن کا نیا پاس ورڈ رکھنا اور انہیں سائن آؤٹ کرنا۔",
  "member:suspend": "رکن کی رسائی معطل کرنا۔",
  "member:update": "رکن کا کردار بدلنا۔",
  "org:delete": "ادارہ حذف کرنا۔",
  "org:read": "ادارے کا پروفائل اور ترتیبات دیکھنا۔",
  "org:transfer_ownership": "ملکیت کسی اور رکن کو منتقل کرنا۔",
  "org:update": "ادارے کے پروفائل اور ترتیبات میں ترمیم کرنا۔",
  "paper:manage": "کسی بھی ٹیسٹ پیپر میں تبدیلی یا اسے حذف کرنا۔",
  "paper:read": "ٹیسٹ پیپر اور سوالات کا بینک دیکھنا۔",
  "paper:write": "ٹیسٹ پیپر بنانا اور اپنے بنائے ہوئے پیپر بدلنا۔",
  "role:assign_permissions": "کسی کردار کی اجازتیں بدلنا۔",
  "role:create": "اپنے کردار بنانا۔",
  "role:delete": "اپنا بنایا ہوا کردار حذف کرنا۔",
  "role:read": "کردار دیکھنا۔",
  "role:update": "کردار کا نام یا تفصیل بدلنا۔",
  "school:archive": "اسکول کو محفوظ شدہ (آرکائیو) کرنا۔",
  "school:create": "ادارے میں نیا اسکول بنانا۔",
  "school:read": "اسکول کا پروفائل دیکھنا۔",
  "school:update": "اسکول کے پروفائل اور ترتیبات میں ترمیم کرنا۔",
  "student:create": "نئے طلبہ داخل کرنا۔",
  "student:delete": "طلبہ کا ریکارڈ ہٹانا۔",
  "student:promote": "کلاس یا سیکشن کو اگلے تعلیمی سال میں ترقی دینا۔",
  "student:read": "طلبہ کا ریکارڈ دیکھنا۔",
  "student:update": "طلبہ کے ریکارڈ میں ترمیم کرنا۔",
  "subject:manage": "مضامین طے کرنا اور انہیں کلاسوں کو دینا۔",
  "subject:read": "مضامین اور کلاسوں کا نصاب دیکھنا۔",
  "teacher:manage": "اساتذہ کو کلاسیں سونپنا۔",
  "teacher:read": "تدریسی عملے کی ذمہ داریاں دیکھنا۔",
  "timetable:manage": "ٹائم ٹیبل میں ترمیم کرنا۔",
  "timetable:read": "ٹائم ٹیبل دیکھنا۔",
  "whatsapp:diary": "ڈائری کی تصویر بھیج کر کلاس کی ڈائری والدین کے واٹس ایپ گروپوں میں پوسٹ کرنا۔",
  "whatsapp:manage": "کلاس کے واٹس ایپ گروپ جوڑنا اور ماہانہ فیس کا پیغام ترتیب دینا۔",
  "whatsapp:read": "جڑے ہوئے واٹس ایپ گروپ اور بھیجے گئے پیغامات دیکھنا۔",
  "whatsapp:send": "کلاس کے واٹس ایپ گروپوں میں پیغامات بھیجنا۔",
};

/** Keyed by the catalog's English category name, which is what the API sends. */
const CATEGORY_UR: Record<string, string> = {
  Organization: "ادارہ",
  Billing: "بلنگ",
  Schools: "اسکول",
  "People & access": "عملہ اور رسائی",
  Guardians: "سرپرست",
  Audit: "آڈٹ",
  Students: "طلبہ",
  Academics: "تعلیمی امور",
  Finance: "مالیات",
  Communication: "رابطہ",
};

const SYSTEM_ROLE_UR: Record<string, { name: string; description: string }> = {
  principal: {
    name: "پرنسپل",
    description: "ادارہ چلاتے ہیں: بلنگ، کیمپس، عملہ، کردار اور اسکول کا تمام ڈیٹا۔",
  },
  teacher: { name: "استاد", description: "تدریسی عملہ۔ حاضری لگاتے اور نمبر درج کرتے ہیں۔" },
  accountant: { name: "اکاؤنٹنٹ", description: "اسکول کی فیس اور انوائسز سنبھالتے ہیں۔" },
};

/**
 * Localizers for backend-owned RBAC text. In English each returns the API's own text.
 *
 * `roleName(code, name)` translates only the three SEEDED roles, recognised by code:
 * a custom role keeps the name its school gave it, in whatever language they typed.
 */
export function useRbacText() {
  const { locale } = useTranslations();
  const ur = locale === "ur";
  return {
    permission: (code: string, fallback: string) => (ur ? (PERMISSION_UR[code] ?? fallback) : fallback),
    category: (name: string) => (ur ? (CATEGORY_UR[name] ?? name) : name),
    roleName: (code: string | null | undefined, name: string) =>
      ur && code ? (SYSTEM_ROLE_UR[code]?.name ?? name) : name,
    roleDescription: (code: string | null | undefined, description: string | null) =>
      ur && code && SYSTEM_ROLE_UR[code] ? SYSTEM_ROLE_UR[code].description : description,
  };
}
