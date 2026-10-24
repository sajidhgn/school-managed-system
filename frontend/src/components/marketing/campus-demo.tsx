import { Building2, Users } from "lucide-react";
import type { CSSProperties } from "react";

import { InView } from "@/components/marketing/in-view";

/**
 * Three campuses of one group, stacked like cards and dealt out into a row on
 * scroll. Each keeps its own students, staff and challan accounts.
 */

const CAMPUSES = [
  { name: "Main Campus", area: "City Centre", students: 640, staff: 38, accounts: 2, hue: "#2447f5" },
  { name: "Girls Campus", area: "Riverside", students: 420, staff: 27, accounts: 1, hue: "#5c626e" },
  { name: "Junior Branch", area: "Hillview", students: 310, staff: 19, accounts: 1, hue: "#9aa3b5" },
];

export function CampusDemo({ description }: { description: string }) {
  return (
    <>
      <p className="sr-only">{description}</p>
      <InView className="mk-campus" dir="ltr" lang="en" threshold={0.4} aria-hidden>
        {CAMPUSES.map((campus, i) => (
          <div
            key={campus.name}
            className="mk-campus__card"
            style={{ "--i": i, "--hue": campus.hue } as CSSProperties}
          >
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl text-white" style={{ background: campus.hue }}>
                <Building2 className="size-5" />
              </span>
              <div className="min-w-0">
                <p className="truncate font-mk-display text-lg leading-tight font-bold">{campus.name}</p>
                <p className="text-sm text-mk-muted">Sunrise Grammar · {campus.area}</p>
              </div>
            </div>
            <dl className="mt-5 grid grid-cols-3 gap-2 border-t border-mk-line pt-4 text-center">
              <div>
                <dt className="text-[11px] text-mk-muted">Students</dt>
                <dd className="font-mk-mono text-lg">{campus.students}</dd>
              </div>
              <div>
                <dt className="text-[11px] text-mk-muted">Staff</dt>
                <dd className="font-mk-mono text-lg">{campus.staff}</dd>
              </div>
              <div>
                <dt className="text-[11px] text-mk-muted">Accounts</dt>
                <dd className="font-mk-mono text-lg">{campus.accounts}</dd>
              </div>
            </dl>
            <p className="mt-4 flex items-center gap-1.5 text-xs text-mk-muted">
              <Users className="size-3.5" />
              Staff here see this campus only
            </p>
          </div>
        ))}
      </InView>
    </>
  );
}
