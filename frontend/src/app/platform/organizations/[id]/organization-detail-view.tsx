"use client";

import { ArrowLeft, School as SchoolIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  ORG_STATUS_LABELS,
  SCHOOL_STATUS_LABELS,
  label,
  type OrganizationDetail,
  type PlanAdminRead,
  type SchoolRead,
} from "@/lib/api/types";
import { formatDate } from "@/lib/utils";

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

export function OrganizationDetailView({
  organization,
  schools,
  plans,
  supportUntil,
}: {
  organization: OrganizationDetail;
  schools: SchoolRead[];
  plans: PlanAdminRead[];
  supportUntil: string | null;
}) {
  const router = useRouter();
  const [planCode, setPlanCode] = useState(organization.plan_code ?? "");
  const [savingPlan, setSavingPlan] = useState(false);
  const readOnlySupport = Boolean(
    supportUntil && new Date(supportUntil).getTime() > Date.now(),
  );

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
          <Badge variant={orgStatusVariant(organization.status)}>
            {label(ORG_STATUS_LABELS, organization.status)}
          </Badge>
        }
      />

      {readOnlySupport ? (
        <div className="mb-6 rounded-lg border border-sky-300 bg-sky-50 p-4 text-sm text-sky-950">
          <strong>Audited read-only support view.</strong> This window expires at{" "}
          {new Date(supportUntil!).toLocaleString()}. No tenant mutation controls are available.
        </div>
      ) : null}

      <dl className="mb-8 grid grid-cols-2 gap-x-6 gap-y-4 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Plan</dt>
          <dd className="font-medium">{organization.plan_name ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Staff</dt>
          <dd className="font-medium tabular-nums">{organization.staff_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Students</dt>
          <dd className="font-medium tabular-nums">{organization.students_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Country</dt>
          <dd className="font-medium">{organization.country ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Billing email</dt>
          <dd className="font-medium">{organization.billing_email ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Trial ends</dt>
          <dd className="font-medium">{formatDate(organization.trial_ends_at)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Current period ends</dt>
          <dd className="font-medium">{formatDate(organization.current_period_end)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Created</dt>
          <dd className="font-medium">{formatDate(organization.created_at)}</dd>
        </div>
      </dl>

      {!readOnlySupport ? <section className="mb-8 rounded-xl border border-border bg-card p-4">
        <h2 className="font-medium">Plan override</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Assign any active plan, including negotiated hidden plans. This action is audited.
        </p>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <select
            className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
            value={planCode}
            onChange={(event) => setPlanCode(event.target.value)}
          >
            {plans.filter((plan) => plan.is_active).map((plan) => (
              <option key={plan.id} value={plan.code}>
                {plan.name} ({plan.code})
              </option>
            ))}
          </select>
          <Button
            onClick={overridePlan}
            loading={savingPlan}
            disabled={!planCode || planCode === organization.plan_code}
          >
            Apply plan
          </Button>
        </div>
      </section> : null}

      <PageHeader title="Schools" description={`${schools.length} campus${schools.length === 1 ? "" : "es"}.`} />

      {schools.length === 0 ? (
        <EmptyState
          icon={SchoolIcon}
          title="No schools yet"
          description="This organization has not created a campus."
        />
      ) : (
        <div className="rounded-xl border border-border bg-card">
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
    </>
  );
}
