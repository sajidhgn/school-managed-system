"use client";

import { ArrowLeft, Ban, Eye, Play, School as SchoolIcon } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  ORG_STATUS_LABELS,
  PLATFORM_AUDIT_ACTION_LABELS,
  SCHOOL_STATUS_LABELS,
  SUBSCRIPTION_STATUS_LABELS,
  label,
  type ImpersonationGrant,
  type OrganizationDetail,
  type PlanAdminRead,
  type PlatformAuditRead,
  type SchoolRead,
} from "@/lib/api/types";
import { cn, formatDate, formatDateTime } from "@/lib/utils";

function orgStatusVariant(status: string) {
  if (status === "active" || status === "trialing") return "success" as const;
  if (status === "suspended" || status === "cancelled") return "destructive" as const;
  return "warning" as const;
}

function schoolStatusVariant(status: string) {
  if (status === "active") return "success" as const;
  if (status === "archived") return "destructive" as const;
  return "neutral" as const;
}

/** The usage counters the summary carries, against the plan limit that caps each. */
const USAGE = [
  { limit: "max_schools", label: "Schools", count: (o: OrganizationDetail) => o.schools_count },
  { limit: "max_students", label: "Students", count: (o: OrganizationDetail) => o.students_count },
  { limit: "max_staff", label: "Staff seats", count: (o: OrganizationDetail) => o.staff_count },
] as const;

export function OrganizationDetailView({
  organization,
  schools,
  plans,
  activity,
  supportUntil,
}: {
  organization: OrganizationDetail;
  schools: SchoolRead[];
  plans: PlanAdminRead[];
  activity: PlatformAuditRead[];
  supportUntil: string | null;
}) {
  const router = useRouter();
  const [planCode, setPlanCode] = useState(organization.plan_code ?? "");
  const [savingPlan, setSavingPlan] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [confirmSuspend, setConfirmSuspend] = useState(false);
  const [reason, setReason] = useState("");
  const [opening, setOpening] = useState(false);
  const readOnlySupport = Boolean(
    supportUntil && new Date(supportUntil).getTime() > Date.now(),
  );
  const suspended = organization.status === "suspended";

  // Assignable plans: every active one, plus the CURRENT plan even if it has since
  // been retired — otherwise the select would show a different plan than the one
  // the organization is actually on.
  const assignable = plans.filter((plan) => plan.is_active || plan.code === organization.plan_code);

  async function overridePlan() {
    if (!planCode || planCode === organization.plan_code) return;
    setSavingPlan(true);
    try {
      await api.post(`/platform/organizations/${organization.id}/plan`, { plan_code: planCode });
      toast({
        title: "Plan overridden",
        description: "The change is recorded in the platform audit log.",
      });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not override plan",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setSavingPlan(false);
    }
  }

  async function setStatus(suspend: boolean) {
    setStatusBusy(true);
    try {
      await api.patch(`/platform/organizations/${organization.id}/status`, {
        suspend,
        reason: reason.trim() || (suspend ? "Suspended from console" : "Reactivated from console"),
      });
      toast({ title: suspend ? `${organization.name} suspended.` : `${organization.name} reactivated.` });
      setReason("");
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "That didn't work",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setStatusBusy(false);
      setConfirmSuspend(false);
    }
  }

  async function viewAs() {
    setOpening(true);
    try {
      const grant = await api.post<ImpersonationGrant>(
        `/platform/organizations/${organization.id}/impersonate`,
        { reason: "Support investigation" },
      );
      router.push(
        `/platform/organizations/${organization.id}?supportUntil=${encodeURIComponent(grant.expires_at)}` as Route,
      );
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not start the support view",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setOpening(false);
    }
  }

  return (
    <>
      <Link
        href="/platform/organizations"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Organizations
      </Link>

      <PageHeader
        title={organization.name}
        description={organization.slug}
        actions={
          <>
            <Badge variant={orgStatusVariant(organization.status)}>
              {label(ORG_STATUS_LABELS, organization.status)}
            </Badge>
            {!readOnlySupport ? (
              <>
                <Button variant="outline" size="sm" onClick={viewAs} loading={opening}>
                  <Eye className="size-4" aria-hidden />
                  View as
                </Button>
                {suspended ? (
                  <Button variant="outline" size="sm" onClick={() => setStatus(false)} loading={statusBusy}>
                    <Play className="size-4" aria-hidden />
                    Reactivate
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setConfirmSuspend(true)}
                    disabled={statusBusy}
                  >
                    <Ban className="size-4" aria-hidden />
                    Suspend
                  </Button>
                )}
              </>
            ) : null}
          </>
        }
      />

      {readOnlySupport ? (
        <div className="mb-6 rounded-lg border border-sky-300 bg-sky-50 p-4 text-sm text-sky-950 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100">
          <strong>Audited read-only support view.</strong> This window expires at{" "}
          {formatDateTime(supportUntil)}. No tenant mutation controls are available.{" "}
          <Link href={`/platform/organizations/${organization.id}` as Route} className="underline">
            Leave support view
          </Link>
        </div>
      ) : null}

      <dl className="mb-6 grid grid-cols-2 gap-x-6 gap-y-4 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-4">
        <Fact term="Plan" value={organization.plan_name ?? "—"} />
        <Fact
          term="Subscription"
          value={
            organization.subscription_status
              ? label(SUBSCRIPTION_STATUS_LABELS, organization.subscription_status)
              : "—"
          }
        />
        <Fact term="Country" value={organization.country ?? "—"} />
        <Fact term="Currency · timezone" value={`${organization.currency} · ${organization.timezone}`} />
        <Fact term="Billing email" value={organization.billing_email ?? "—"} />
        <Fact term="Trial ends" value={formatDate(organization.trial_ends_at)} />
        <Fact term="Current period ends" value={formatDate(organization.current_period_end)} />
        <Fact term="Created" value={formatDate(organization.created_at)} />
      </dl>

      <section className="mb-6 rounded-xl border border-border bg-card p-4">
        <h2 className="font-medium">Usage against plan</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Over a limit, existing records stay readable but new ones are refused.
        </p>
        <ul className="mt-4 grid gap-4 sm:grid-cols-3">
          {USAGE.map((row) => {
            const used = row.count(organization);
            const raw = organization.limits?.[row.limit];
            const limit = raw === undefined || raw === null ? null : Number(raw);
            const unlimited = limit === -1;
            const ratio = limit && limit > 0 ? used / limit : 0;
            return (
              <li key={row.limit}>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="text-muted-foreground">{row.label}</span>
                  <span className="tabular-nums">
                    <span className="font-medium">{used.toLocaleString()}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      / {limit === null ? "—" : unlimited ? "∞" : limit.toLocaleString()}
                    </span>
                  </span>
                </div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      ratio >= 1 ? "bg-destructive" : ratio >= 0.85 ? "bg-warning" : "bg-chart-1",
                    )}
                    style={{ width: unlimited || limit === null ? "0%" : `${Math.min(100, ratio * 100)}%` }}
                  />
                </div>
                {ratio >= 1 ? <p className="mt-1 text-xs text-destructive">At or over the limit</p> : null}
              </li>
            );
          })}
        </ul>
      </section>

      {!readOnlySupport ? (
        <section className="mb-8 rounded-xl border border-border bg-card p-4">
          <h2 className="font-medium">Plan override</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Assign any active plan, including negotiated hidden plans. This action is audited.
          </p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
            <NativeSelect
              aria-label="Plan"
              className="flex-1"
              value={planCode}
              onChange={(event) => setPlanCode(event.target.value)}
            >
              {/* Without this, an organization with no plan shows the first option as
                  if selected while the state is "", and Apply stays disabled. */}
              {!organization.plan_code ? (
                <option value="" disabled>
                  Choose a plan…
                </option>
              ) : null}
              {assignable.map((plan) => (
                <option key={plan.id} value={plan.code}>
                  {plan.name} ({plan.code}){plan.is_public ? "" : " · hidden"}
                  {plan.is_active ? "" : " · retired"}
                  {plan.code === organization.plan_code ? " · current" : ""}
                </option>
              ))}
            </NativeSelect>
            <Button
              onClick={overridePlan}
              loading={savingPlan}
              disabled={!planCode || planCode === organization.plan_code}
            >
              Apply plan
            </Button>
          </div>
        </section>
      ) : null}

      <PageHeader title="Schools" description={`${schools.length} campus${schools.length === 1 ? "" : "es"}.`} />

      {schools.length === 0 ? (
        <EmptyState
          icon={SchoolIcon}
          title="No schools yet"
          description="This organization has not created a campus."
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>School</TableHead>
                <TableHead>City</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schools.map((school) => (
                <TableRow key={school.id}>
                  <TableCell>
                    <div className="font-medium">{school.name}</div>
                    <div className="text-xs text-muted-foreground">{school.code}</div>
                  </TableCell>
                  <TableCell>{school.city ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={schoolStatusVariant(school.status)}>
                      {label(SCHOOL_STATUS_LABELS, school.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>{formatDate(school.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <section className="mt-8">
        <PageHeader
          title="Operator activity"
          description="Suspensions, plan changes and support views on this organization."
          actions={
            <Link
              href={`/platform/audit?organization_id=${organization.id}` as Route}
              className="text-sm text-muted-foreground hover:text-foreground hover:underline"
            >
              Full history
            </Link>
          }
        />
        {activity.length === 0 ? (
          <p className="text-sm text-muted-foreground">No operator has acted on this organization yet.</p>
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border bg-card">
            {activity.map((entry) => {
              const why = typeof entry.audit_metadata?.reason === "string" ? entry.audit_metadata.reason : null;
              return (
                <li key={entry.id} className="flex flex-col gap-0.5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:gap-4">
                  <span className="w-40 shrink-0 text-xs text-muted-foreground">{formatDateTime(entry.created_at)}</span>
                  <span className="font-medium">{label(PLATFORM_AUDIT_ACTION_LABELS, entry.action)}</span>
                  {why ? <span className="text-muted-foreground">“{why}”</span> : null}
                  <span className="text-xs text-muted-foreground sm:ms-auto">{entry.actor_email ?? "System"}</span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={confirmSuspend}
        onOpenChange={(open) => !open && setConfirmSuspend(false)}
        title={`Suspend ${organization.name}?`}
        description={
          <span className="block space-y-3">
            <span className="block">
              Their admin panel becomes READ-ONLY. Staff can still sign in, read everything and
              export their data — only writes are refused. Nothing is deleted.
            </span>
            <textarea
              className="block min-h-20 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
              placeholder="Reason (kept in the audit log)"
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </span>
        }
        confirmLabel="Suspend"
        variant="destructive"
        loading={statusBusy}
        onConfirm={() => setStatus(true)}
      />
    </>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="truncate font-medium" title={value}>
        {value}
      </dd>
    </div>
  );
}
