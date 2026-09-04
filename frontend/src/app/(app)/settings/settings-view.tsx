"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ColorListInput, THEME_COLOR_PATTERN } from "@/components/ui/color-input";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogoInput } from "@/components/ui/logo-input";
import { NativeSelect } from "@/components/ui/native-select";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { organization as orgApi } from "@/lib/api/resources";
import {
  ORG_STATUS_LABELS,
  label,
  type MeResponse,
  type MemberRead,
  type OrganizationRead,
} from "@/lib/api/types";
import { CURRENCY_CODES, timezonesForCurrency } from "@/lib/currency-timezones";

/*
 * The full IANA list is only the fallback: normally the timezone dropdown is
 * narrowed to the zones of the selected currency's regions. The English
 * currency name is fixed-locale on purpose — a locale-dependent label would
 * render differently on server and client and trip hydration.
 */
const TIMEZONES: string[] = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
})();

const currencyNames = new Intl.DisplayNames(["en"], { type: "currency" });

function currencyLabel(code: string): string {
  try {
    const name = currencyNames.of(code);
    return name && name !== code ? `${code} — ${name}` : code;
  } catch {
    // `of` throws on a syntactically invalid code; a stored value is shown as-is.
    return code;
  }
}

function withCurrent(options: string[], current: string): string[] {
  // A stored value outside ICU's list (an old tzdata alias, say) must still
  // appear, otherwise the select would silently show — and save — a different one.
  return options.includes(current) ? options : [current, ...options];
}

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
  canTransferOwnership,
  ownershipCandidates,
}: {
  user: MeResponse;
  organization: OrganizationRead | null;
  canEditOrg: boolean;
  canTransferOwnership: boolean;
  ownershipCandidates: MemberRead[];
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [name, setName] = useState(organization?.name ?? "");
  const [billingEmail, setBillingEmail] = useState(organization?.billing_email ?? "");
  const [logoUrl, setLogoUrl] = useState(organization?.logo_url ?? "");
  const [themeColors, setThemeColors] = useState<string[]>(organization?.theme_colors ?? []);
  const [currency, setCurrency] = useState(organization?.currency ?? "USD");
  const [timezone, setTimezone] = useState(organization?.timezone ?? "UTC");

  // Zones where the chosen currency circulates; empty means "unknown", in
  // which case the dropdown falls back to the full IANA list.
  const currencyZones = timezonesForCurrency(currency);
  const timezoneOptions = currencyZones.length ? currencyZones : TIMEZONES;

  function changeCurrency(code: string) {
    setCurrency(code);
    const zones = timezonesForCurrency(code);
    // Follow the currency: keep the timezone only if it still fits, otherwise
    // pick the first matching zone (single-zone countries thus auto-select).
    if (zones.length && !zones.includes(timezone)) {
      setTimezone(zones[0]);
    }
  }
  const [saving, setSaving] = useState(false);
  const [newOwnerMembershipId, setNewOwnerMembershipId] = useState("");
  const [confirmTransfer, setConfirmTransfer] = useState(false);

  async function save() {
    if (themeColors.some((color) => !THEME_COLOR_PATTERN.test(color))) {
      toast({
        variant: "destructive",
        title: "Each theme colour must be a 6-digit hex value, like #1D4ED8.",
      });
      return;
    }
    setSaving(true);
    try {
      await orgApi.update({
        name,
        billing_email: billingEmail || null,
        // Empty means "unbranded", sent as an explicit null so the PATCH clears
        // the stored value rather than leaving it (omitted = unchanged). The API
        // spells "no palette" as null, never [].
        logo_url: logoUrl.trim() || null,
        theme_colors: themeColors.length ? themeColors : null,
        currency,
        timezone,
      });
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

  async function transferOwnership() {
    if (!newOwnerMembershipId) return;
    setSaving(true);
    try {
      await orgApi.transferOwnership(newOwnerMembershipId);
      toast({ title: "Ownership transferred", description: "Your organization-owner session has ended." });
      window.location.assign("/select-school");
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not transfer ownership",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setSaving(false);
      setConfirmTransfer(false);
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

            {/*
              Branding lives at BOTH levels on purpose. This is the organization-wide
              default every branch inherits; a branch that wants its own identity
              overrides it on its school page, field by field. That is the whole
              "single or individual" story — there is no mode switch to forget.
            */}
            <div className="grid gap-4 border-t border-border pt-4">
              <h3 className="text-sm font-medium">Branding</h3>

              <div className="grid gap-1.5">
                <Label htmlFor="org-logo">Logo</Label>
                <LogoInput
                  id="org-logo"
                  value={logoUrl}
                  disabled={!canEditOrg}
                  onChange={setLogoUrl}
                />
              </div>

              <div className="grid gap-1.5">
                <Label>Theme colours</Label>
                <ColorListInput
                  values={themeColors}
                  disabled={!canEditOrg}
                  onChange={setThemeColors}
                />
              </div>

              <p className="text-xs text-muted-foreground">
                Used on student cards and printed headers. Every branch uses this
                branding unless it sets its own — a branch overrides it from its page
                under Schools.
              </p>
            </div>

            <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="org-currency">{t.settings.currency}</Label>
                <NativeSelect
                  id="org-currency"
                  value={currency}
                  disabled={!canEditOrg}
                  onChange={(event) => changeCurrency(event.target.value)}
                >
                  {withCurrent(CURRENCY_CODES, currency).map((code) => (
                    <option key={code} value={code}>
                      {currencyLabel(code)}
                    </option>
                  ))}
                </NativeSelect>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="org-timezone">{t.settings.timezone}</Label>
                <NativeSelect
                  id="org-timezone"
                  value={timezone}
                  disabled={!canEditOrg}
                  onChange={(event) => setTimezone(event.target.value)}
                >
                  {withCurrent(timezoneOptions, timezone).map((zone) => (
                    <option key={zone} value={zone}>
                      {zone}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>

            <dl className="grid gap-3 border-t border-border pt-4 text-sm">
              <Row label={t.settings.identifier} value={organization.slug} />
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

      {canTransferOwnership ? (
        <section className="mt-8 rounded-xl border border-destructive/30 bg-card p-5">
          <h2 className="font-medium">Transfer ownership</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Promote an active member to organization owner. Your org-level owner access is removed atomically.
          </p>
          {ownershipCandidates.length > 0 ? (
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <select
                className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
                value={newOwnerMembershipId}
                onChange={(event) => setNewOwnerMembershipId(event.target.value)}
                aria-label="New owner"
              >
                <option value="">Choose an active member</option>
                {ownershipCandidates.map((member) => (
                  <option key={member.membership_id} value={member.membership_id}>
                    {member.full_name} ({member.email})
                  </option>
                ))}
              </select>
              <Button
                variant="destructive"
                disabled={!newOwnerMembershipId}
                onClick={() => setConfirmTransfer(true)}
              >
                Transfer ownership
              </Button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              Invite an active member before transferring ownership.
            </p>
          )}
        </section>
      ) : null}

      <ConfirmDialog
        open={confirmTransfer}
        onOpenChange={setConfirmTransfer}
        title="Transfer organization ownership?"
        description="The selected member receives billing and organization-wide authority immediately. Your organization-owner membership is removed."
        confirmLabel="Transfer ownership"
        variant="destructive"
        loading={saving}
        onConfirm={transferOwnership}
      />
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
