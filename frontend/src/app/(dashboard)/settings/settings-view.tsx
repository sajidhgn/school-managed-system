"use client";

import * as React from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { PlanBadge, SchoolStatusBadge, UserStatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback, Separator, Skeleton } from "@/components/ui/misc";
import { useCurrentSchool } from "@/hooks/use-schools";
import { ApiError } from "@/lib/api/errors";
import { USER_ROLE_LABELS, type SchoolRead, type UserRead } from "@/lib/api/types";
import { formatDate, formatDateTime, initials } from "@/lib/utils";

export function SettingsView({ user }: { user: UserRead }) {
  return (
    <>
      <PageHeader title="Settings" description="Your account, school details, and appearance." />

      <div className="space-y-6">
        <ProfileCard user={user} />
        {/* Rendered as a child so the /schools/current request is never fired
            for super admins, who have no school and would 404. */}
        {user.role === "school_admin" ? <SchoolCard /> : null}
        <AppearanceCard />
      </div>
    </>
  );
}

// --- Profile ---------------------------------------------------------------

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-3 sm:items-center sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm sm:col-span-2">{children}</dd>
    </div>
  );
}

function ProfileCard({ user }: { user: UserRead }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>
          Your account details. Editing these isn&apos;t supported by the API yet — contact your
          administrator to make changes.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <Avatar className="size-11">
            <AvatarFallback className="text-sm">{initials(user.full_name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="truncate font-medium">{user.full_name}</p>
            <p className="truncate text-sm text-muted-foreground">{user.email}</p>
          </div>
        </div>

        <Separator />

        <dl className="divide-y divide-border">
          <DetailRow label="Role">{USER_ROLE_LABELS[user.role]}</DetailRow>
          <DetailRow label="Status">
            <UserStatusBadge status={user.status} />
          </DetailRow>
          <DetailRow label="Email verified">
            <Badge variant={user.email_verified ? "success" : "warning"}>
              {user.email_verified ? "Verified" : "Not verified"}
            </Badge>
          </DetailRow>
          <DetailRow label="Two-factor auth">
            <Badge variant={user.two_factor_enabled ? "success" : "neutral"}>
              {user.two_factor_enabled ? "Enabled" : "Disabled"}
            </Badge>
          </DetailRow>
          <DetailRow label="Last sign-in">
            <span className="text-muted-foreground">{formatDateTime(user.last_login_at)}</span>
          </DetailRow>
          <DetailRow label="Member since">
            <span className="text-muted-foreground">{formatDate(user.created_at)}</span>
          </DetailRow>
        </dl>
      </CardContent>
    </Card>
  );
}

// --- School ----------------------------------------------------------------

function SchoolCard() {
  const query = useCurrentSchool();
  const school = query.data;

  if (query.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>School</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-2/3" />
        </CardContent>
      </Card>
    );
  }

  // A missing school is a "nothing to show" case, not a failure worth an alarm.
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    if (missing) return null;
    return (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  }

  if (!school) return null;
  return <SchoolDetails school={school} />;
}

/**
 * School details — read-only.
 *
 * Deliberately not a form. `PATCH /schools/{id}` is guarded by
 * `require_super_admin` (backend/app/modules/tenancy/router.py), so a
 * school_admin editing their own school would get a 403 on save. Rendering an
 * editable form here would promise an action the API refuses.
 *
 * If the backend later allows a school_admin to update their own school (RLS
 * already scopes them to that row), this becomes a form again and
 * `useUpdateSchool` is ready for it.
 */
function SchoolDetails({ school }: { school: SchoolRead }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>School</CardTitle>
        <CardDescription>
          Details for {school.name}. Changes are made by the platform team — contact them to
          update these.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          <DetailRow label="Name">{school.name}</DetailRow>
          <DetailRow label="Identifier">@{school.slug}</DetailRow>
          <DetailRow label="Contact email">{school.email}</DetailRow>
          <DetailRow label="Phone">{school.phone ?? "—"}</DetailRow>
          <DetailRow label="City">{school.city ?? "—"}</DetailRow>
          <DetailRow label="Country">{school.country ?? "—"}</DetailRow>
          <DetailRow label="Address">{school.address ?? "—"}</DetailRow>
          <DetailRow label="Student capacity">{school.max_students}</DetailRow>
          <DetailRow label="Status">
            <SchoolStatusBadge status={school.status} />
          </DetailRow>
          <DetailRow label="Plan">
            <PlanBadge plan={school.plan} />
          </DetailRow>
        </dl>
      </CardContent>
    </Card>
  );
}


// --- Appearance ------------------------------------------------------------

const THEMES = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

function AppearanceCard() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // The stored theme is unknown during SSR, so the selected state is only
  // rendered after mount to avoid a hydration mismatch.
  React.useEffect(() => setMounted(true), []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>Choose how the dashboard looks on this device.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Theme">
          {THEMES.map(({ value, label, icon: Icon }) => {
            const active = mounted && theme === value;
            return (
              <Button
                key={value}
                type="button"
                variant={active ? "default" : "outline"}
                aria-pressed={active}
                onClick={() => setTheme(value)}
              >
                <Icon />
                {label}
              </Button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
