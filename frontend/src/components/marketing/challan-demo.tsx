import { Scissors } from "lucide-react";

import { InView } from "@/components/marketing/in-view";

/**
 * A three-part bank challan. On scroll, scissors run down the perforations,
 * the copies come apart, and the bank's PAID stamp lands on the school copy.
 * Below `lg` the copies are a fanned deck instead, with the school copy on top.
 *
 * The figures are an example, but they add up: tuition, exam fee, stationery
 * and arrears, less a sibling concession, with the late fee after the due date.
 */

const COPIES = [
  { kind: "bank", label: "Bank copy" },
  { kind: "school", label: "School copy" },
  { kind: "student", label: "Student copy" },
] as const;

const DETAILS: [string, string][] = [
  ["Student", "Ayesha Khan"],
  ["Class", "9-A · Roll 14"],
  ["Month", "October 2026"],
  ["Due date", "10 Oct 2026"],
];

const CHARGES: [string, string][] = [
  ["Tuition fee", "6,500"],
  ["Exam fee", "800"],
  ["Stationery · 2 copies", "240"],
  ["Arrears (September)", "1,200"],
  ["Sibling concession", "−650"],
];

export function ChallanDemo({ description }: { description: string }) {
  return (
    <>
      <p className="sr-only">{description}</p>
      <InView className="mk-challan" dir="ltr" lang="en" threshold={0.4} aria-hidden>
        <div className="mk-challan__set">
          <Scissors className="mk-scissors size-5" style={{ insetInlineStart: "15.5rem" }} />
          <Scissors className="mk-scissors size-5" style={{ insetInlineStart: "31rem" }} />
          {COPIES.map(({ kind, label }) => (
            <div key={kind} className={`mk-copy mk-copy--${kind} relative`}>
              <div className="mk-copy__label">
                <span>{label}</span>
                <span className="num tracking-normal">No. 2610-0412</span>
              </div>
              <p className="font-mk-display text-[13.5px] leading-tight font-bold">
                Sunrise Grammar School
              </p>
              <p className="text-[10px] text-[#5b6382]">Main Campus · Monthly fee challan</p>
              <div className="mk-copy__rule" />
              {DETAILS.map(([k, v]) => (
                <div key={k} className="mk-copy__row">
                  <span className="text-[#5b6382]">{k}</span>
                  <span className="font-bold">{v}</span>
                </div>
              ))}
              <div className="mk-copy__rule" />
              {CHARGES.map(([k, v]) => (
                <div key={k} className="mk-copy__row">
                  <span>{k}</span>
                  <span className="num">{v}</span>
                </div>
              ))}
              <div className="mk-copy__row mk-copy__total">
                <span>Payable by due date</span>
                <span className="num">Rs 8,090</span>
              </div>
              <div className="mk-copy__row mt-1 text-[#5b6382]">
                <span>After due date</span>
                <span className="num">Rs 8,390</span>
              </div>
              <div className="mk-copy__rule" />
              <p className="text-[10px] text-[#5b6382]">
                Account <span className="num text-[#1a1f33]">0100 2345 6789</span>
              </p>
              <p className="mt-4 border-t border-dotted border-[#9aa3bd] pt-1 text-[9.5px] text-[#5b6382]">
                Depositor&apos;s signature
              </p>
              {kind === "school" ? (
                <span className="mk-stamp">
                  <b>Paid</b>
                  <small>12 Oct 2026</small>
                </span>
              ) : null}
            </div>
          ))}
        </div>
      </InView>
    </>
  );
}
