import { getLocale } from "@/lib/i18n/server";
import { cn } from "@/lib/utils";

/**
 * The band of the product's subjects under the home hero, in the visitor's
 * language, with its one-line label. Every subject is a shipped feature.
 *
 * Two rows slide without end, the first left to right and the second right to
 * left. It is all CSS (site.css, `.mk-ticker`): each row holds its items six
 * times and moves by exactly half its width, so the loop has no seam. Hovering
 * pauses it, and with reduced motion it stands still.
 *
 * Decorative: everything here is said again, in words, further down the page.
 */

const ROWS = {
  en: [
    ["Fee challans", "WhatsApp diary", "Test papers", "Attendance", "Exams", "Admissions", "ID cards", "Every campus"],
    ["Concessions", "Late fees", "Ledgers", "Result cards", "Roles", "Audit log", "Urdu", "Search"],
  ],
  ur: [
    ["فیس چالان", "واٹس ایپ ڈائری", "ٹیسٹ پیپرز", "حاضری", "امتحانات", "داخلے", "شناختی کارڈ", "ہر کیمپس"],
    ["رعایتیں", "لیٹ فیس", "کھاتے", "رزلٹ کارڈ", "کردار", "آڈٹ لاگ", "اردو", "تلاش"],
  ],
};

export async function Marquee({ label }: { label: string }) {
  const locale = await getLocale();
  const urdu = locale === "ur";

  return (
    <div className="mk-ticker-band">
      <p className="mk-container text-center text-sm font-semibold text-mk-muted">{label}</p>
      <div className="mk-ticker" aria-hidden>
        {ROWS[locale].map((items, row) => (
          <div key={row} className="mk-ticker__row" data-direction={row % 2 ? "left" : "right"}>
            {Array.from({ length: 6 }, () => items).flat().map((item, i) => (
              <span key={i} className={cn("mk-ticker__item", urdu && "mk-ur-deco")} dir={urdu ? "rtl" : "ltr"}>
                <span className="mk-ticker__dot" />
                {item}
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
