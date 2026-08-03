"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { organization as orgApi } from "@/lib/api/resources";
import {
  ORG_STATUS_LABELS,
  label,
  type MeResponse,
  type OrganizationRead,
} from "@/lib/api/types";

/**
 * Account and organization settings.
 *
 * Two sections: the person, and the organization they are in. The organization
 * block is read-only for anyone without `org:update` — shown rather than hidden,
 * because a principal genuinely needs to see their organization's name and billing
 * address even though changing them is the owner's job.
 */
export function SettingsView({
  user,
  organization,
  canEditOrg,
}: {
  user: MeResponse;
  organization: OrganizationRead | null;
  canEditOrg: boolean;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [name, setName] = useState(organization?.name ?? "");
  const [billingEmail, setBillingEmail] = useState(organization?.billing_email ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await orgApi.update({ name, billing_email: billingEmail || null });
      toast({ title: t.settings.organizationUpdated });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not save",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <PageHeader title={t.settings.title} />

      <section className="mb-8 rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 font-medium">{t.settings.yourAccount}</h2>
        <dl className="grid gap-3 text-sm">
          <Row label={t.common.name} value={user.full_name} />
          <Row label={t.common.email} value={user.email} />
          <Row label={t.settings.activeContext} value={user.school_name ?? user.organization_name ?? "—"} />
          <Row label={t.common.role} value={user.role_code ?? "—"} />
        </dl>
        <p className="mt-4 text-xs text-muted-foreground">
          {/* Honest about scope rather than showing a disabled form: these are not
              editable in this release, and a greyed-out input implies otherwise. */}
          {t.settings.accountReadOnly}
        </p>
      </section>

      {organization ? (
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="mb-4 flex items-center gap-3">
            <h2 className="font-medium">{t.settings.organization}</h2>
            <Badge variant={organization.status === "active" ? "success" : "warning"}>
              {label(ORG_STATUS_LABELS, organization.status)}
            </Badge>
          </div>

          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="org-name">{t.common.name}</Label>
              <Input
                id="org-name"
                value={name}
                disabled={!canEditOrg}
                onChange={(event) => setName(event.target.value)}
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="billing-email">{t.settings.billingEmail}</Label>
              <Input
                id="billing-email"
                type="email"
                value={billingEmail}
                disabled={!canEditOrg}
                onChange={(event) => setBillingEmail(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t.settings.billingEmailHint}
              </p>
            </div>

            <dl className="grid gap-3 border-t border-border pt-4 text-sm">
              <Row label={t.settings.identifier} value={organization.slug} />
              <Row label={t.settings.currency} value={organization.currency} />
              <Row label={t.settings.timezone} value={organization.timezone} />
            </dl>

            {canEditOrg ? (
              <div>
                <Button onClick={save} disabled={saving}>
                  {saving ? t.common.saving : t.settings.saveChanges}
                </Button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t.settings.ownerOnly}
              </p>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Row({ label: rowLabel, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{rowLabel}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
