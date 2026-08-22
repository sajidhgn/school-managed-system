import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { serverGetRequired } from "@/lib/api/server";
import type { AuditLogRead } from "@/lib/api/types";
import { requireSchoolContext } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Audit log" };

/**
 * The school's audit trail.
 *
 * A read-only server component — there is nothing to mutate, and the list is
 * append-only by design. The API returns newest-first with keyset pagination; this
 * view shows the most recent page, which is what an administrator checking "who
 * changed this?" actually wants.
 *
 * `before`/`after` are rendered as a compact diff rather than raw JSON. The backend
 * stores only the CHANGED fields, so the object is small enough to read — which is
 * itself a deliberate schema decision: whole-row snapshots would have made this
 * table a second, less-protected copy of the student database.
 */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ before?: string }>;
}) {
  const params = await searchParams;
  const [user, t] = await Promise.all([requireSchoolContext(), getTranslations()]);
  const query = new URLSearchParams({ limit: "51" });
  if (params.before) query.set("before", params.before);
  const entries = await serverGetRequired<AuditLogRead[]>(
    `/schools/${user.school_id}/audit-logs?${query}`,
  );
  const page = entries.slice(0, 50);

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader
        title={t.audit.title}
        description={t.audit.subtitle}
      />

      {entries.length === 0 ? (
        <EmptyState
          title={t.audit.emptyTitle}
          description={t.audit.emptyBody}
        />
      ) : (
        <div className="rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.audit.when}</TableHead>
                <TableHead>{t.audit.action}</TableHead>
                <TableHead>{t.audit.entity}</TableHead>
                <TableHead>{t.audit.change}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {new Date(entry.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="font-medium">{entry.action}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {entry.entity_type ?? "—"}
                  </TableCell>
                  <TableCell className="max-w-md">
                    <Diff before={entry.before} after={entry.after} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {entries.length > 0 ? (
        <div className="mt-4 flex justify-between">
          {params.before ? <Button asChild variant="outline"><Link href="/audit">Newest</Link></Button> : <span />}
          {entries.length > 50 ? (
            <Button asChild variant="outline">
              <Link href={`/audit?before=${encodeURIComponent(page.at(-1)!.created_at)}`}>Older</Link>
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Diff({
  before,
  after,
}: {
  before: Record<string, unknown> | null | undefined;
  after: Record<string, unknown> | null | undefined;
}) {
  if (!before && !after) return <span className="text-muted-foreground">—</span>;

  // Union of both sides, so a field that was only added or only removed still shows.
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];

  return (
    <ul className="grid gap-0.5 text-xs">
      {keys.slice(0, 4).map((key) => (
        <li key={key} className="truncate">
          <span className="text-muted-foreground">{key}: </span>
          {before?.[key] !== undefined ? (
            <span className="text-destructive line-through">{format(before[key])}</span>
          ) : null}
          {before?.[key] !== undefined && after?.[key] !== undefined ? " → " : null}
          {after?.[key] !== undefined ? (
            <span className="text-success">{format(after[key])}</span>
          ) : null}
        </li>
      ))}
      {keys.length > 4 ? (
        <li className="text-muted-foreground">+{keys.length - 4} more</li>
      ) : null}
    </ul>
  );
}

function format(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length > 3 ? `${value.length} items` : value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
