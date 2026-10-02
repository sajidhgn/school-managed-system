"use client";

import type { Route } from "next";
import { Ban, Eye, MoreHorizontal, Play, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  ORG_STATUS_LABELS,
  label,
  type ImpersonationGrant,
  type OrganizationSummary,
} from "@/lib/api/types";

/**
 * Operator view of every organization.
 *
 * =============================================================================
 * SUSPENSION IS READ-ONLY, AND THE CONFIRMATION SAYS SO
 * =============================================================================
 *   Spec §6.3: a suspended organization keeps read and export access. Only writes
 *   are refused.
 *
 *   The dialog states that plainly, because an operator about to suspend a school
 *   mid-term needs to know they are not cutting a principal off from their own
 *   student records. That policy is not incidental — in several jurisdictions those
 *   are records the school is legally required to be able to produce, and
 *   withholding them would be leverage no software vendor should hold.
 */
export function OrganizationsView({
  organizations,
  hasMore,
  offset,
  pageSize,
  q,
  status,
}: {
  organizations: OrganizationSummary[];
  hasMore: boolean;
  offset: number;
  pageSize: number;
  q: string;
  status: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [search, setSearch] = useState(q);
  const [busy, setBusy] = useState<string | null>(null);
  const [suspending, setSuspending] = useState<OrganizationSummary | null>(null);
  const filtering = Boolean(q || status);

  /** Filters live in the URL so they survive refresh and can be shared. */
  function navigate(next: { q?: string; status?: string; offset?: number }) {
    const params = new URLSearchParams();
    const nextQ = next.q ?? q;
    const nextStatus = next.status ?? status;
    if (nextQ) params.set("q", nextQ);
    if (nextStatus) params.set("status", nextStatus);
    if (next.offset) params.set("offset", String(next.offset));
    const query = params.toString();
    router.push(`${pathname}${query ? `?${query}` : ""}` as Route);
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    navigate({ q: search.trim(), offset: 0 });
  }

  async function viewAs(org: OrganizationSummary) {
    try {
      const grant = await api.post<ImpersonationGrant>(
        `/platform/organizations/${org.id}/impersonate`,
        { reason: "Support investigation" },
      );
      router.push(
        `/platform/organizations/${org.id}?supportUntil=${encodeURIComponent(grant.expires_at)}` as Route,
      );
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not start the support view",
        description: error instanceof ApiError ? error.message : undefined,
      });
    }
  }

  async function setStatus(org: OrganizationSummary, suspend: boolean, reason?: string) {
    setBusy(org.id);
    try {
      await api.patch(`/platform/organizations/${org.id}/status`, { suspend, reason });
      toast({ title: suspend ? `${org.name} suspended.` : `${org.name} reactivated.` });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "That didn't work",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(null);
      setSuspending(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Organizations"
        description={
          organizations.length === 0
            ? "Every customer account on the platform."
            : `Showing ${offset + 1}–${offset + organizations.length}${filtering ? " matching" : ""}.`
        }
      />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <form onSubmit={submitSearch} className="flex flex-1 gap-2 sm:max-w-sm" role="search">
          <Input
            type="search"
            placeholder="Search by name or identifier…"
            aria-label="Search organizations"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Button type="submit" variant="outline" size="icon">
            <Search className="size-4" aria-hidden />
            <span className="sr-only">Search</span>
          </Button>
        </form>
        <NativeSelect
          aria-label="Filter by status"
          className="sm:w-44"
          value={status}
          onChange={(event) => navigate({ status: event.target.value, offset: 0 })}
        >
          <option value="">All statuses</option>
          {Object.entries(ORG_STATUS_LABELS).map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </NativeSelect>
      </div>

      {organizations.length === 0 ? (
        <EmptyState
          title="No organizations"
          description={filtering ? "Nothing matches these filters." : "None have signed up yet."}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Organization</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-end">Schools</TableHead>
                <TableHead className="text-end">Staff</TableHead>
                <TableHead className="text-end">Students</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {organizations.map((org) => (
                <TableRow key={org.id}>
                  <TableCell>
                    <Link
                      href={`/platform/organizations/${org.id}`}
                      className="font-medium hover:underline"
                    >
                      {org.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{org.slug}</div>
                  </TableCell>
                  <TableCell>{org.plan_name ?? "—"}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        org.status === "active" || org.status === "trialing"
                          ? "success"
                          : org.status === "suspended" || org.status === "cancelled"
                            ? "destructive"
                            : "warning"
                      }
                    >
                      {label(ORG_STATUS_LABELS, org.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-end tabular-nums">{org.schools_count}</TableCell>
                  <TableCell className="text-end tabular-nums">{org.staff_count}</TableCell>
                  <TableCell className="text-end tabular-nums">{org.students_count}</TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" disabled={busy !== null}>
                          <MoreHorizontal className="size-4" aria-hidden />
                          <span className="sr-only">Actions for {org.name}</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-56">
                        <DropdownMenuItem onSelect={() => viewAs(org)} className="gap-2">
                          <Eye className="size-4" aria-hidden />
                          View as (audited, read-only)
                        </DropdownMenuItem>

                        <DropdownMenuSeparator />

                        {org.status === "suspended" ? (
                          <DropdownMenuItem
                            onSelect={() => setStatus(org, false)}
                            className="gap-2"
                          >
                            <Play className="size-4" aria-hidden />
                            Reactivate
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem
                            onSelect={() => setSuspending(org)}
                            className="gap-2 text-destructive focus:text-destructive"
                          >
                            <Ban className="size-4" aria-hidden />
                            Suspend
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {offset > 0 || hasMore ? (
        <div className="mt-4 flex justify-between">
          {offset > 0 ? (
            <Button variant="outline" onClick={() => navigate({ offset: Math.max(0, offset - pageSize) })}>
              Newer
            </Button>
          ) : (
            <span />
          )}
          {hasMore ? (
            <Button variant="outline" onClick={() => navigate({ offset: offset + pageSize })}>
              Older
            </Button>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={suspending !== null}
        onOpenChange={(open) => !open && setSuspending(null)}
        title={`Suspend ${suspending?.name}?`}
        description="Their admin panel becomes READ-ONLY. Staff can still sign in, read everything and export their data — only writes are refused. Nothing is deleted."
        confirmLabel="Suspend"
        variant="destructive"
        loading={busy !== null}
        onConfirm={() => suspending && setStatus(suspending, true, "Suspended from console")}
      />
    </>
  );
}
