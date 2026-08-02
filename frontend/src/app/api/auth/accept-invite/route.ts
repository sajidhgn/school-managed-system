import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { getAccessToken, readTokens, setSession } from "@/lib/auth/session";

/**
 * Accept an invitation (spec §7.2).
 *
 * Handled here rather than through the BFF because acceptance MINTS A SESSION: the
 * backend signs the invitee straight in, scoped to the membership they just
 * accepted. Making a brand-new user log in again immediately after choosing a
 * password is friction with no security benefit — they proved inbox control and set
 * the credential in the same request.
 *
 * =============================================================================
 * THE EXISTING SESSION IS FORWARDED ON PURPOSE
 * =============================================================================
 *   An invitee may already be signed in — they work at another school on the
 *   platform. The backend needs to see that session, because it enforces that the
 *   signed-in account's email matches the invited address EXACTLY.
 *
 *   That check is what stops someone accepting an invitation forwarded to them. So
 *   forwarding the token is not a convenience; omitting it would silently skip a
 *   guard, and the accept would succeed for the wrong person.
 */

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const token = await getAccessToken();

  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-token-transport": "body",
    "x-forwarded-for": request.headers.get("x-forwarded-for") ?? "",
    "user-agent": request.headers.get("user-agent") ?? "",
  };
  if (token) headers.authorization = `Bearer ${token}`;

  const upstream = await fetch(backendUrl("/invitations/accept"), {
    method: "POST",
    headers,
    body,
    cache: "no-store",
  });

  const payload = await upstream.text();

  if (!upstream.ok) {
    return new NextResponse(payload, {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }

  // Acceptance mints a session scoped to the new membership. Adopting it here is
  // what lets the invitee land in the admin panel already signed in.
  //
  // For an EXISTING user this replaces their previous context with the school they
  // just joined — which is the right default, since accepting an invitation is an
  // explicit statement of where they intend to work next. Their other memberships
  // remain available through the switcher.
  const tokens = readTokens(upstream);
  if (tokens) await setSession(tokens);

  return new NextResponse(payload, {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
