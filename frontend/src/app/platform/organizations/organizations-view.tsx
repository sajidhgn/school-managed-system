"use client";

import { Ban, Eye, MoreHorizontal, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

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
}: {
  organizations: OrganizationSummary[];
}) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [suspending, setSuspending] = useState<OrganizationSummary | null>(null);

  const filtered = search
    ? organizations.filter(
        (org) =>
          org.name.toLowerCase().includes(search.toLowerCase()) ||
          org.slug.toLowerCase().includes(search.toLowerCase()),
      )
    : organizations;

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
        description={`${organizations.length} on the platform.`}
      />

      <div className="mb-4 max-w-sm">
        <Input
          type="search"
          placeholder="Search by name or identifier…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="No organizations"
          description={search ? "Nothing matches that search." : "None have signed up yet."}
        />
      ) : (
        <div className="rounded-xl border border-border bg-card">
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
              {filtered.map((org) => (
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
                        <DropdownMenuItem
                          onSelect={async () => {
                            try {
                              const grant = await api.post<ImpersonationGrant>(
                                `/platform/organizations/${org.id}/impersonate`,
                                { reason: "Support investigation" },
                              );
                              router.push(
                                `/platform/organizations/${org.id}?supportUntil=${encodeURIComponent(grant.expires_at)}`,
                              );
                            } catch {
                              toast({ variant: "destructive", title: "Could not start" });
                            }
                          }}
                          className="gap-2"
                        >
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
