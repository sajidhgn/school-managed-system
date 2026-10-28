import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { clientHeaders, relayGuardianLogin } from "@/lib/auth/guardian-login";
import { getAccessToken } from "@/lib/auth/session";

/**
 * Open one school group: straight after a verify that returned `select_required`,
 * or to switch groups mid-session. Either way the guardian access cookie is the
 * credential, and the backend re-checks that the chosen group is still this
 * parent's before minting the session.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const token = await getAccessToken("guardian");
  if (!token) {
    return NextResponse.json(
      { status: 401, code: "TOKEN_MISSING", detail: "Your sign-in expired. Request a new code." },
      { status: 401 },
    );
  }

  const upstream = await fetch(backendUrl("/guardian/auth/context"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-token-transport": "body",
      authorization: `Bearer ${token}`,
      ...clientHeaders(request),
    },
    body: await request.text(),
    cache: "no-store",
  });
  return relayGuardianLogin(upstream);
}
