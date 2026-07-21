import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";

/**
 * Register a school and its first admin.
 *
 * No session is established: the backend puts the user in
 * `pending_verification` and emails a code, so the client is sent on to
 * /verify-email rather than into the dashboard.
 */
export async function POST(request: NextRequest) {
  const body = await request.json();

  const upstream = await fetch(backendUrl("/auth/register"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}
