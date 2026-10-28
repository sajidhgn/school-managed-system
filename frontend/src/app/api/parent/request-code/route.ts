import { NextRequest } from "next/server";

import { forwardPublicMutation } from "@/lib/api/public-route";

/**
 * Ask for a parent-portal sign-in code. Anonymous: the parent has proved nothing yet.
 *
 * The backend answers identically for a registered and an unregistered number, and
 * sends the code on WhatsApp after responding, so nothing here can reveal which.
 */

export const dynamic = "force-dynamic";

export function POST(request: NextRequest) {
  return forwardPublicMutation(request, "/guardian/auth/request-code");
}
