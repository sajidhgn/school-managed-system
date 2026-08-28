import { NextRequest, NextResponse } from "next/server";

import type { SchoolRead } from "@/lib/api/types";
import { fetchWithSession, setActiveSchoolId } from "@/lib/auth/session";

/**
 * Choose which campus an ORG-LEVEL user is looking at.
 *
 * NOT a context switch. `/api/auth/context` re-mints the token pair because it
 * changes WHO you are acting as; this changes only which school the school-scoped
 * pages render, for someone whose authority already covers all of them. Nothing is
 * re-issued, no permission changes, and the membership stays org-level.
 *
 * The school is verified against `GET /schools` — the caller's own visible list —
 * before the cookie is written. Not for safety: every school-scoped route takes its
 * id from the path and is authorised server-side regardless of this cookie. It is so
 * a stale or hand-edited value fails HERE, with a clear message, instead of turning
 * every page into a 404 the user cannot explain.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const { school_id: schoolId } = (await request.json()) as {
    school_id?: string;
  };

  if (!schoolId) {
    return NextResponse.json({ detail: "school_id is required." }, { status: 400 });
  }

  const response = await fetchWithSession("/schools", {}, "tenant", true);
  if (!response || !response.ok) {
    return NextResponse.json({ detail: "Your session has expired." }, { status: 401 });
  }

  const schools = (await response.json()) as SchoolRead[];
  const school = schools.find((s) => s.id === schoolId);
  if (!school) {
    return NextResponse.json({ detail: "No such school in this organization." }, { status: 404 });
  }

  await setActiveSchoolId(school.id);
  return NextResponse.json(school, { status: 200 });
}
