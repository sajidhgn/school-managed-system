"use client";

import * as React from "react";
import { Building2, MoreHorizontal, Plus, X } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { PlanBadge, SchoolStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useApproveSchool, useSchools, useSuspendSchool } from "@/hooks/use-schools";
import { SCHOOL_STATUS_LABELS, type SchoolRead, type SchoolStatus } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";
import { SchoolFormDialog } from "./school-form-dialog";

const ALL = "__all__";
const PAGE_SIZE = 20;
const COLUMN_COUNT = 7;

type LifecycleAction = "approve" | "suspend";

export function SchoolsView() {
  const [status, setStatus] = React.useState<SchoolStatus | "">("");
  const [page, setPage] = React.useState(1);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<SchoolRead | null>(null);
  const [confirming, setConfirming] = React.useState<{
    school: SchoolRead;
    action: LifecycleAction;
  } | null>(null);

  const approveSchool = useApproveSchool();
  const suspendSchool = useSuspendSchool();

  // A filter change invalidates the page number — page 4 of the old result set
  // is meaningless against the new one.
  React.useEffect(() => {
    setPage(1);
  }, [status]);

  const query = useSchools({
    status_filter: status || null,
    page,
    size: PAGE_SIZE,
    sort_by: "created_at",
    sort_dir: "desc",
  });

  const schools = query.data?.items ?? [];
  const meta = query.data?.meta;
  const pendingOnly = status === "pending_approval";

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(school: SchoolRead) {
    setEditing(school);
    setFormOpen(true);
  }

  async function confirmLifecycle() {
    if (!confirming) return;
    const { school, action } = confirming;
    const mutation = action === "approve" ? approveSchool : suspendSchool;
    await mutation.mutateAsync(school.id);
    setConfirming(null);
  }

  return (
    <>
      <PageHeader
        title="Schools"
        description="Onboard tenants, approve sign-up requests, and manage subscriptions."
        actions={
          <Button onClick={openCreate}>
            <Plus />
            Onboard school
          </Button>
        }
      />

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          {/* The pending queue is the super admin's actual daily job, so it gets
              a one-click shortcut instead of living only inside the dropdown. */}
          <Button
            variant={pendingOnly ? "default" : "outline"}
            size="sm"
            onClick={() => setStatus(pendingOnly ? "" : "pending_approval")}
          >
            Pending approval
          </Button>

          <Select
            value={status || ALL}
            onValueChange={(value) => setStatus(value === ALL ? "" : (value as SchoolStatus))}
          >
            <SelectTrigger className="w-48" aria-label="Filter by status">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {Object.entries(SCHOOL_STATUS_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {status ? (
            <Button variant="ghost" size="sm" onClick={() => setStatus("")}>
              <X />
              Clear
            </Button>
          ) : null}
        </div>

        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>School</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Student cap</TableHead>
                  <TableHead>Onboarded</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {query.isLoading ? (
                  <TableSkeleton columns={COLUMN_COUNT} />
                ) : schools.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={COLUMN_COUNT} className="p-0">
                      <EmptyState
                        icon={Building2}
                        title={status ? "No matching schools" : "No schools yet"}
                        description={
                          status
                            ? "No school currently has this status."
                            : "Onboard your first school to start managing tenants."
                        }
                        action={
                          status ? (
                            <Button variant="outline" size="sm" onClick={() => setStatus("")}>
                              Clear filter
                            </Button>
                          ) : (
                            <Button size="sm" onClick={openCreate}>
                              <Plus />
                              Onboard school
                            </Button>
                          )
                        }
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  schools.map((school) => (
                    <TableRow key={school.id}>
                      <TableCell>
                        <span className="font-medium text-foreground">{school.name}</span>
                        <span className="block text-xs text-muted-foreground">{school.slug}</span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{school.email}</TableCell>
                      <TableCell>
                        <SchoolStatusBadge status={school.status} />
                      </TableCell>
                      <TableCell>
                        <PlanBadge plan={school.plan} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {school.max_students.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(school.created_at)}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Actions for ${school.name}`}
                            >
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => openEdit(school)}>
                              Edit
                            </DropdownMenuItem>
                            {school.status === "pending_approval" ? (
                              <DropdownMenuItem
                                onClick={() => setConfirming({ school, action: "approve" })}
                              >
                                Approve
                              </DropdownMenuItem>
                            ) : null}
                            {school.status === "active" ? (
                              <DropdownMenuItem
                                destructive
                                onClick={() => setConfirming({ school, action: "suspend" })}
                              >
                                Suspend
                              </DropdownMenuItem>
                            ) : null}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            {meta ? (
              <Pagination meta={meta} onPageChange={setPage} disabled={query.isFetching} />
            ) : null}
          </>
        )}
      </Card>

      <SchoolFormDialog open={formOpen} onOpenChange={setFormOpen} school={editing} />

      <ConfirmDialog
        open={Boolean(confirming)}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={confirming?.action === "approve" ? "Approve school?" : "Suspend school?"}
        description={
          <>
            <span className="font-medium text-foreground">{confirming?.school.name}</span>{" "}
            {confirming?.action === "approve"
              ? "will become active and its staff will be able to sign in."
              : "will be suspended and its staff will no longer be able to sign in."}
          </>
        }
        confirmLabel={confirming?.action === "approve" ? "Approve school" : "Suspend school"}
        variant={confirming?.action === "approve" ? "default" : "destructive"}
        loading={approveSchool.isPending || suspendSchool.isPending}
        onConfirm={() => void confirmLifecycle()}
      />
    </>
  );
}
