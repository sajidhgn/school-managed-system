"use client";

import {
  ArrowLeft,
  Archive,
  Check,
  Mail,
  MapPin,
  Pencil,
  Phone,
  ShieldCheck,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { useTranslations } from "@/components/providers/i18n-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ColorListInput, THEME_COLOR_PATTERN } from "@/components/ui/color-input";
import { Input } from "@/components/ui/input";
import { LogoInput } from "@/components/ui/logo-input";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { schools as schoolsApi } from "@/lib/api/resources";
import {
  PERMISSIONS,
  SCHOOL_STATUS_LABELS,
  label,
  type SchoolRead,
} from "@/lib/api/types";

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/**
 * One campus in full.
 *
 * The counts are links, not decoration. Landing here from the school list, the next
 * question is almost always "who works here?" or "what is still pending?" — and for
 * an org-level user those pages render whichever campus is ACTIVE, not whichever one
 * they happen to be reading about. So following one of them selects this campus
 * first; otherwise clicking "12 staff" on School B would show School A's staff,
 * which is the kind of quiet mismatch nobody thinks to double-check.
 */
export function SchoolDetailView({
  school,
  memberCount,
  pendingInvitationCount,
  roleCount,
  canSelectCampus,
  isActiveCampus,
}: {
  school: SchoolRead;
  memberCount: number;
  pendingInvitationCount: number;
  roleCount: number;
  canSelectCampus: boolean;
  isActiveCampus: boolean;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(school.name);
  const [editCity, setEditCity] = useState(school.city ?? "");
  const [editLogoUrl, setEditLogoUrl] = useState(school.logo_url ?? "");
  const [editThemeColors, setEditThemeColors] = useState<string[]>(school.theme_colors ?? []);
  const [formError, setFormError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [busy, setBusy] = useState(false);

  /** Make this the active campus, then go wherever the reader was heading. */
  async function openScoped(href: string) {
    setBusy(true);
    try {
      if (canSelectCampus && !isActiveCampus) {
        await schoolsApi.setActive(school.id);
      }
      // Push before refresh so the shared layout (sidebar) is re-fetched for the
      // destination; a refresh issued before the push is superseded by it.
      router.push(href as never);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!editName.trim()) return;
    if (editThemeColors.some((color) => !THEME_COLOR_PATTERN.test(color))) {
      setFormError("Each theme colour must be a 6-digit hex value, like #1D4ED8.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await schoolsApi.update(school.id, {
        name: editName.trim(),
        city: editCity.trim() || null,
        // Explicit nulls: an emptied branding field REVERTS this campus to the
        // organization's branding (null means inherit, not "no logo"). An empty
        // palette is likewise sent as null — the API has one spelling for it.
        logo_url: editLogoUrl.trim() || null,
        theme_colors: editThemeColors.length ? editThemeColors : null,
      });
      toast({ title: `${editName.trim()} updated.` });
      setEditing(false);
      router.refresh();
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    setBusy(true);
    try {
      await schoolsApi.archive(school.id);
      toast({ title: `${school.name} archived.` });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not archive this school",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
      setArchiving(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <Link
        href="/schools"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t.schools.title}
      </Link>

      <PageHeader
        title={school.name}
        description={`${school.code}${school.city ? ` · ${school.city}` : ""}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={school.status === "active" ? "success" : "neutral"}>
              {label(SCHOOL_STATUS_LABELS, school.status)}
            </Badge>
            {canSelectCampus && school.status === "active" ? (
              isActiveCampus ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Check className="size-4" aria-hidden />
                  Active campus
                </span>
              ) : (
                <Button variant="outline" size="sm" disabled={busy} onClick={() => openScoped("/dashboard")}>
                  Work in this campus
                </Button>
              )
            ) : null}
            <Can permission={PERMISSIONS.schoolUpdate}>
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil className="size-4" aria-hidden />
                Edit
              </Button>
            </Can>
            {school.status === "active" ? (
              <Can permission={PERMISSIONS.schoolArchive}>
                <Button variant="ghost" size="sm" onClick={() => setArchiving(true)}>
                  <Archive className="size-4" aria-hidden />
                  Archive
                </Button>
              </Can>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Can permission={PERMISSIONS.memberRead}>
          <CountCard
            icon={Users}
            label={t.nav.members}
            value={memberCount}
            disabled={busy}
            onOpen={() => openScoped("/members")}
          />
        </Can>
        <Can permission={PERMISSIONS.invitationRead}>
          <CountCard
            icon={Mail}
            label={t.nav.invitations}
            value={pendingInvitationCount}
            disabled={busy}
            onOpen={() => openScoped("/members?invite=1")}
          />
        </Can>
        <Can permission={PERMISSIONS.roleRead}>
          <CountCard
            icon={ShieldCheck}
            label={t.nav.roles}
            value={roleCount}
            disabled={busy}
            onOpen={() => openScoped("/roles")}
          />
        </Can>
      </div>

      <section className="mt-8 rounded-xl border border-border bg-card">
        <h2 className="border-b border-border px-5 py-3 text-sm font-medium">Details</h2>
        <dl className="grid gap-x-8 gap-y-4 p-5 sm:grid-cols-2">
          <Detail term="Short code" value={school.code} />
          <Detail term="Status" value={label(SCHOOL_STATUS_LABELS, school.status)} />
          <Detail term="City" value={school.city} icon={MapPin} />
          <Detail term="Address" value={school.address} />
          <Detail term="Email" value={school.email} icon={Mail} />
          <Detail term="Phone" value={school.phone} icon={Phone} />
          <Detail
            term="Academic year starts"
            value={MONTHS[(school.academic_year_start_month ?? 1) - 1] ?? null}
          />
          <Detail term="Timezone" value={school.timezone} />
          <Detail term="Language" value={school.locale} />
          <Detail
            term="Created"
            value={school.created_at ? new Date(school.created_at).toLocaleDateString() : null}
          />
        </dl>
      </section>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit {school.name}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{t.onboarding.schoolName}</span>
              <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{t.onboarding.city}</span>
              <Input value={editCity} onChange={(e) => setEditCity(e.target.value)} />
            </label>
            <div className="grid gap-1.5 text-sm">
              <span className="font-medium">Logo</span>
              <LogoInput value={editLogoUrl} onChange={setEditLogoUrl} />
            </div>
            <div className="grid gap-1.5 text-sm">
              <span className="font-medium">Theme colours</span>
              <ColorListInput values={editThemeColors} onChange={setEditThemeColors} />
            </div>
            <p className="text-xs text-muted-foreground">
              Branding here applies to this branch only. Leave a field empty to use
              your organization&apos;s branding from Settings.
            </p>
            {formError ? (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(false)} disabled={busy}>
              {t.common.cancel}
            </Button>
            <Button onClick={save} disabled={busy || !editName.trim()}>
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={archiving}
        onOpenChange={setArchiving}
        title={`Archive ${school.name}?`}
        description="Its records stay readable and exportable. Staff lose the ability to add new data there until it is restored."
        confirmLabel="Archive"
        onConfirm={archive}
      />
    </div>
  );
}

function CountCard({
  icon: Icon,
  label: labelText,
  value,
  disabled,
  onOpen,
}: {
  icon: typeof Users;
  label: string;
  value: number;
  disabled: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={disabled}
      className="rounded-xl border border-border bg-card p-4 text-start transition-colors hover:border-primary/60 disabled:opacity-60"
    >
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="size-4" aria-hidden />
        {labelText}
      </span>
      <span className="mt-1 block text-2xl font-semibold tabular-nums">{value}</span>
    </button>
  );
}

function Detail({
  term,
  value,
  icon: Icon,
}: {
  term: string;
  value: string | null | undefined;
  icon?: typeof MapPin;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{term}</dt>
      <dd className="mt-0.5 flex items-center gap-1.5 text-sm">
        {Icon && value ? <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden /> : null}
        <span className="truncate">{value || "—"}</span>
      </dd>
    </div>
  );
}
