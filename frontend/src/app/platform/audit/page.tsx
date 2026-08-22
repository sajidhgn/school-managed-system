import type { Metadata } from "next";
import Link from "next/link";

import { PlatformChrome } from "@/components/platform/platform-chrome";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { serverGetRequired } from "@/lib/api/server";
import type { PlatformAuditRead } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";
import { formatDate } from "@/lib/utils";

export const metadata: Metadata = { title: "Platform audit" };
export const dynamic = "force-dynamic";

export default async function PlatformAuditPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string }>;
}) {
  const [admin, params] = await Promise.all([requirePlatformAdmin(), searchParams]);
  const offset = Math.max(0, Number(params.offset ?? 0) || 0);
  const entries = await serverGetRequired<PlatformAuditRead[]>(
    `/platform/audit-logs?limit=51&offset=${offset}`,
    "platform",
  );
  const page = entries.slice(0, 50);

  return (
    <PlatformChrome adminName={admin.full_name}>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Platform audit log</h1>
        <p className="text-sm text-muted-foreground">Authentication, support access, plan changes and tenant controls.</p>
      </div>
      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Target organization</TableHead>
              <TableHead>Source IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>{formatDate(entry.created_at)}</TableCell>
                <TableCell><Badge variant="outline">{entry.action}</Badge></TableCell>
                <TableCell className="font-mono text-xs">{entry.target_organization_id ?? "—"}</TableCell>
                <TableCell>{entry.ip ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="mt-4 flex justify-between">
        {offset > 0 ? <Button asChild variant="outline"><Link href={`/platform/audit?offset=${Math.max(0, offset - 50)}`}>Newer</Link></Button> : <span />}
        {entries.length > 50 ? <Button asChild variant="outline"><Link href={`/platform/audit?offset=${offset + 50}`}>Older</Link></Button> : null}
      </div>
    </PlatformChrome>
  );
}
