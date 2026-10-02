import type { Metadata, Route } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { PlatformChrome } from "@/components/platform/platform-chrome";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { serverGetRequired } from "@/lib/api/server";
import { PLATFORM_AUDIT_ACTION_LABELS, label, type PlatformAuditRead } from "@/lib/api/types";
import { requirePlatformAdmin } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/utils";

export const metadata: Metadata = { title: "Platform audit" };
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

/** Filter chips. Values are action PREFIXES — the endpoint matches with startsWith. */
const FILTERS = [
  { value: "", label: "Everything" },
  { value: "platform_admin.", label: "Sign-ins" },
  { value: "platform.organization_", label: "Organization controls" },
  { value: "platform.impersonation_", label: "Support views" },
  { value: "platform.plan_", label: "Plan catalog" },
] as const;

function actionVariant(action: string) {
  if (action.endsWith("login_failed") || action.endsWith("reuse_detected") || action.endsWith("suspended"))
    return "destructive" as const;
  if (action.startsWith("platform.impersonation")) return "warning" as const;
  if (action.startsWith("platform_admin.")) return "neutral" as const;
  return "default" as const;
}

/** One readable line from the metadata each action writes (see platform_admin/service.py). */
function auditDetail(meta: Record<string, unknown>): string | null {
  if (typeof meta.reason === "string" && meta.reason) {
    // Login failures record a machine code ("invalid_credentials"); free-text
    // reasons from operators are quoted as written.
    return /^[a-z_]+$/.test(meta.reason) ? meta.reason.replaceAll("_", " ") : `“${meta.reason}”`;
  }
  if (typeof meta.plan_code === "string") return `→ ${meta.plan_code}`;
  if (Array.isArray(meta.changed)) return `Changed: ${meta.changed.join(", ")}`;
  if (typeof meta.code === "string") return meta.code;
  return null;
}

export default async function PlatformAuditPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string; action?: string; organization_id?: string }>;
}) {
  const [admin, params] = await Promise.all([requirePlatformAdmin(), searchParams]);
  const offset = Math.max(0, Number(params.offset ?? 0) || 0);
  const action = params.action ?? "";
  const organizationId = params.organization_id ?? "";

  const query = new URLSearchParams({ limit: String(PAGE_SIZE + 1), offset: String(offset) });
  if (action) query.set("action", action);
  if (organizationId) query.set("organization_id", organizationId);

  const entries = await serverGetRequired<PlatformAuditRead[]>(
    `/platform/audit-logs?${query}`,
    "platform",
  );
  const page = entries.slice(0, PAGE_SIZE);

  const href = (next: { action?: string; offset?: number }) => {
    const p = new URLSearchParams();
    const a = next.action ?? action;
    if (a) p.set("action", a);
    if (organizationId) p.set("organization_id", organizationId);
    if (next.offset) p.set("offset", String(next.offset));
    const s = p.toString();
    return `/platform/audit${s ? `?${s}` : ""}` as Route;
  };

  return (
    <PlatformChrome adminName={admin.full_name}>
      <PageHeader
        title="Platform audit log"
        description="Authentication, support access, plan changes and tenant controls."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Button key={f.value} asChild size="sm" variant={f.value === action ? "default" : "outline"}>
            <Link href={href({ action: f.value, offset: 0 })} aria-current={f.value === action ? "true" : undefined}>
              {f.label}
            </Link>
          </Button>
        ))}
        {organizationId ? (
          <Button asChild size="sm" variant="ghost">
            <Link href={`/platform/audit${action ? `?action=${action}` : ""}` as Route}>
              Clear organization filter ×
            </Link>
          </Button>
        ) : null}
      </div>

      {page.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          No audit entries match.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Operator</TableHead>
                <TableHead>Organization</TableHead>
                <TableHead>Details</TableHead>
                <TableHead>Source IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.map((entry) => {
                const detail = auditDetail(entry.audit_metadata ?? {});
                return (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap">{formatDateTime(entry.created_at)}</TableCell>
                    <TableCell>
                      <Badge variant={actionVariant(entry.action)} title={entry.action}>
                        {label(PLATFORM_AUDIT_ACTION_LABELS, entry.action)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{entry.actor_email ?? "—"}</TableCell>
                    <TableCell>
                      {entry.target_organization_id ? (
                        <Link
                          href={`/platform/organizations/${entry.target_organization_id}` as Route}
                          className="hover:underline"
                        >
                          {entry.target_organization_name ?? (
                            <span className="font-mono text-xs">{entry.target_organization_id}</span>
                          )}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="max-w-64 truncate text-sm text-muted-foreground" title={detail ?? undefined}>
                      {detail ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{entry.ip ?? "—"}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="mt-4 flex justify-between">
        {offset > 0 ? (
          <Button asChild variant="outline">
            <Link href={href({ offset: Math.max(0, offset - PAGE_SIZE) })}>Newer</Link>
          </Button>
        ) : (
          <span />
        )}
        {entries.length > PAGE_SIZE ? (
          <Button asChild variant="outline">
            <Link href={href({ offset: offset + PAGE_SIZE })}>Older</Link>
          </Button>
        ) : null}
      </div>
    </PlatformChrome>
  );
}
