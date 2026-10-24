import type { CSSProperties } from "react";

import { InView } from "@/components/marketing/in-view";
import { cn } from "@/lib/utils";

/**
 * A section's register filling in day by day, then each student's percentage
 * counting up. Late counts as attended, as it does on the report card.
 * Phones show the last six days so the grid fits without scrolling.
 */

const DAYS: [string, number][] = [
  ["M", 5],
  ["T", 6],
  ["W", 7],
  ["T", 8],
  ["F", 9],
  ["M", 12],
  ["T", 13],
  ["W", 14],
];

const ROWS: [string, string][] = [
  ["Ayesha Khan", "PPPPPPPP"],
  ["Bilal Ahmed", "PPAPPPLP"],
  ["Fatima Zahra", "PPPPAPPP"],
  ["Hamza Raza", "PLPPPPPP"],
  ["Maryam Siddiqui", "PPPPPPPA"],
  ["Usman Tariq", "APPPPAPP"],
];

/** The first two days are dropped on phones. */
const hideOnPhone = (col: number) => (col < 2 ? "max-sm:hidden" : undefined);

function percent(marks: string): number {
  const attended = [...marks].filter((m) => m !== "A").length;
  return Math.round((attended / marks.length) * 100);
}

export function RegisterDemo({ description }: { description: string }) {
  return (
    <>
      <p className="sr-only">{description}</p>
      <InView
        className="rounded-2xl border border-mk-line bg-mk-card p-3 shadow-[0_24px_48px_-32px_rgb(15_20_45/0.45)] sm:p-5"
        threshold={0.35}
        dir="ltr"
        lang="en"
        aria-hidden
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-1 pb-3">
          <p className="font-mk-display text-lg font-bold">Class 9-A · Register</p>
          <p className="text-sm text-mk-muted">October · Period 1</p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_repeat(6,1.75rem)_3rem] items-center sm:grid-cols-[minmax(0,1fr)_repeat(8,2rem)_3.5rem]">
          <span />
          {DAYS.map(([day, date], col) => (
            <span
              key={col}
              className={cn("text-center text-[11px] leading-tight text-mk-muted", hideOnPhone(col))}
            >
              {day}
              <br />
              <span className="font-mk-mono text-mk-text">{date}</span>
            </span>
          ))}
          <span className="text-end text-[11px] text-mk-muted">%</span>

          {ROWS.map(([name, marks], row) => (
            <div key={name} className="contents">
              <span className="truncate border-t border-mk-line py-2 pe-2 text-sm">{name}</span>
              {[...marks].map((mark, col) => (
                <span
                  key={col}
                  className={cn("grid place-items-center border-t border-mk-line py-1.5", hideOnPhone(col))}
                >
                  <span
                    className={cn(
                      "mk-mark",
                      mark === "P" && "mk-mark--p",
                      mark === "A" && "mk-mark--a",
                      mark === "L" && "mk-mark--l",
                    )}
                    style={{ "--c": col, "--r": row } as CSSProperties}
                  >
                    {mark}
                  </span>
                </span>
              ))}
              <span
                className={cn(
                  "mk-pct border-t border-mk-line py-2 text-end text-sm font-bold",
                  percent(marks) < 80 ? "text-mk-ink" : "text-mk-text",
                )}
                style={{ "--target": percent(marks) } as CSSProperties}
              />
            </div>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 px-1 text-xs text-mk-muted">
          <span>
            <b className="font-mk-hand text-sm text-mk-ink">P</b> present
          </span>
          <span>
            <b className="me-1 inline-grid size-5 place-items-center rounded-full bg-mk-text font-mk-hand text-[11px] text-mk-paper">
              A
            </b>
            absent
          </span>
          <span>
            <b className="font-mk-hand text-sm text-mk-muted">L</b> late, counts as attended
          </span>
        </div>
      </InView>
    </>
  );
}
