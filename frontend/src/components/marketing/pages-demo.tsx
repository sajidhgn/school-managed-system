import { Check } from "lucide-react";
import type { CSSProperties } from "react";

import { InView } from "@/components/marketing/in-view";

/**
 * A chapter uploaded as loose phone photos, sorting itself into printed-page
 * order, with one stray page from another chapter set aside for review. This is
 * what the books agent does (docs/modules/books.md).
 *
 * Positions are in container-width units, so the scene scales as one piece.
 * `x, y, r` is where a photo lands when dropped; `ox, oy, or` is its sorted place.
 */

type Page = {
  no: number;
  title?: string;
  heading?: string;
  x: number;
  y: number;
  r: number;
  ox: number;
  oy: number;
  or: number;
};

// Listed in upload order, not page order: the DOM order is the pile's stacking.
const PILE: Page[] = [
  { no: 40, x: 23, y: 5, r: 14, ox: 49.5, oy: 12, or: 0 },
  { no: 38, x: 7, y: 21, r: 9, ox: 18.5, oy: 12, or: 0 },
  { no: 112, title: "Chapter 7 · Percentages", x: 33, y: 23, r: -18, ox: 83, oy: 13, or: 6 },
  { no: 41, x: 51, y: 23, r: 4, ox: 65, oy: 12, or: 0 },
  { no: 39, heading: "Exercise 4.3", x: 64, y: 19, r: -6, ox: 34, oy: 12, or: 0 },
  { no: 37, title: "Chapter 4 · Linear equations", x: 40, y: 3, r: -12, ox: 3, oy: 12, or: 0 },
];

const SORTED = [...PILE].sort((a, b) => a.no - b.no).map((p) => p.no);

const TEXT_WIDTHS = [92, 100, 86, 97, 70, 100, 90, 64];

export function PagesDemo({ description }: { description: string }) {
  return (
    <>
      <p className="sr-only">{description}</p>
      <InView className="mk-pages" dir="ltr" lang="en" threshold={0.45} aria-hidden>
        <div className="mk-pages__tray">
          <p className="mk-pages__tray-label">Needs review</p>
          <p className="mk-pages__why">p. 112 is from chapter 7</p>
        </div>
        {PILE.map((page) => (
          <div
            key={page.no}
            className="mk-page"
            style={
              {
                "--x": page.x,
                "--y": page.y,
                "--r": page.r,
                "--ox": page.ox,
                "--oy": page.oy,
                "--or": page.or,
                "--i": SORTED.indexOf(page.no),
              } as CSSProperties
            }
          >
            {page.title ? <p className="mk-page__title">{page.title}</p> : null}
            {TEXT_WIDTHS.slice(0, page.title ? 6 : 8).map((width, i) => (
              <span key={i} className="mk-page__text" style={{ width: `${width}%` }} />
            ))}
            {page.heading ? <p className="mk-page__title">{page.heading}</p> : null}
            <span className="mk-page__no">{page.no}</span>
          </div>
        ))}
        <span className="mk-pages__ready">
          <Check className="size-3.5" />
          Chapter 4 · pages 37–41 · ready
        </span>
      </InView>
    </>
  );
}
