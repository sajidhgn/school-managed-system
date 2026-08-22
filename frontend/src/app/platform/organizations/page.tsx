import type { Metadata } from "next";

import { OrganizationsView } from "./organizations-view";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { serverGetRequired } from "@/lib/api/server";
import type { OrganizationSummary } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Organizations" };

/**
 * Every organization on the platform.
 *
 * `requirePlatformAdmin()` validates the operator's session against the backend,
 * which also re-reads the account and refuses a deactivated one — the most
 * privileged role on the system is the last place a 15-minute revocation delay is
 * acceptable.
 */
export default async function OrganizationsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const [admin, params] = await Promise.all([requirePlatformAdmin(), searchParams]);

  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);

  const organizations = await serverGetRequired<OrganizationSummary[]>(
    `/platform/organizations${query.toString() ? `?${query}` : ""}`,
    "platform",
  );

  return (
    <PlatformChrome adminName={admin.full_name}>
      <OrganizationsView organizations={organizations} />
    </PlatformChrome>
  );
}
