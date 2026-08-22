import { NextRequest } from "next/server";

import { forwardPublicMutation } from "@/lib/api/public-route";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return forwardPublicMutation(request, "/auth/reset-password");
}
