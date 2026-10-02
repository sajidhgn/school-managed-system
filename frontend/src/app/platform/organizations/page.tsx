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
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

export default async function OrganizationsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; offset?: string }>;
}) {
  const [admin, params] = await Promise.all([requirePlatformAdmin(), searchParams]);
  const offset = Math.max(0, Number(params.offset ?? 0) || 0);

  // Search and status filter run on the SERVER, across every organization. Filtering
  // only the rows already fetched would silently miss everything past the first page.
  // One extra row tells us whether an "Older" page exists without a count query.
  const query = new URLSearchParams({ limit: String(PAGE_SIZE + 1), offset: String(offset) });
  if (params.q) query.set("q", params.q);
  if (params.status) query.set("status", params.status);

  const rows = await serverGetRequired<OrganizationSummary[]>(
    `/platform/organizations?${query}`,
    "platform",
  );

  return (
    <PlatformChrome adminName={admin.full_name}>
      <OrganizationsView
        organizations={rows.slice(0, PAGE_SIZE)}
        hasMore={rows.length > PAGE_SIZE}
        offset={offset}
        pageSize={PAGE_SIZE}
        q={params.q ?? ""}
        status={params.status ?? ""}
      />
    </PlatformChrome>
  );
}
