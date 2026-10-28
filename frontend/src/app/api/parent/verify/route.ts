import { NextRequest } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { clientHeaders, relayGuardianLogin } from "@/lib/auth/guardian-login";

/**
 * Exchange the WhatsApp code for a portal session.
 *
 * Three outcomes, all 200: signed in, choose a school group, or no access. See
 * `relayGuardianLogin` for which cookies each one writes.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const upstream = await fetch(backendUrl("/guardian/auth/verify"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-token-transport": "body",
      ...clientHeaders(request),
    },
    body: await request.text(),
    cache: "no-store",
  });
  return relayGuardianLogin(upstream);
}
