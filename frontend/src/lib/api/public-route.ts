import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";

/**
 * Forward one explicitly allowlisted anonymous mutation to FastAPI.
 *
 * Callers supply a compile-time path; browser input can never select the upstream
 * endpoint. This keeps the generic BFF authenticated while letting the handful of
 * genuine public forms work before a user has a session.
 */
export async function forwardPublicMutation(
  request: NextRequest,
  backendPath: "/auth/forgot-password" | "/auth/reset-password" | "/students/admissions",
): Promise<NextResponse> {
  const upstream = await fetch(backendUrl(backendPath), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": request.headers.get("x-forwarded-for") ?? "",
      "user-agent": request.headers.get("user-agent") ?? "",
    },
    body: await request.text(),
    cache: "no-store",
  });

  const headers = new Headers({
    "content-type": upstream.headers.get("content-type") ?? "application/json",
  });
  for (const name of ["x-request-id", "retry-after"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers,
  });
}
