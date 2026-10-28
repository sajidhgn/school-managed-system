import { NextResponse } from "next/server";

import { fetchWithSession } from "@/lib/auth/session";

/**
 * Download one of a child's challans with the parent's session.
 *
 * A plain link target: the browser saves the PDF as it would any download, and the
 * guardian token stays in its httpOnly cookie. The portal endpoint decides whether
 * this parent may have it -- another child's challan, a draft or a voided one is a
 * 404 there, and is passed through as one here.
 */

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ studentId: string; voucherId: string }> },
) {
  const { studentId, voucherId } = await params;
  // Checked here so nothing but two ids can ever be spliced into the upstream path.
  if (!UUID.test(studentId) || !UUID.test(voucherId)) {
    return NextResponse.json({ status: 404, detail: "Challan not found." }, { status: 404 });
  }

  const upstream = await fetchWithSession(
    `/portal/children/${studentId}/fees/${voucherId}/pdf`,
    { method: "GET" },
    "guardian",
    true,
  );
  if (!upstream) {
    return NextResponse.redirect(new URL("/parent/login", request.url));
  }
  if (!upstream.ok) {
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": "application/pdf",
      "content-disposition":
        upstream.headers.get("content-disposition") ?? 'attachment; filename="challan.pdf"',
      "cache-control": "private, no-store",
    },
  });
}
