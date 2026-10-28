import type { Metadata } from "next";
import { GraduationCap } from "lucide-react";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoMark } from "@/components/marketing/logo";
import { Card, CardContent } from "@/components/ui/card";
import { serverGet } from "@/lib/api/server";
import type { GuardianChildRead } from "@/lib/api/types";
import { requireGuardian } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";
import { formatDate } from "@/lib/utils";

import { ParentSignOutButton } from "./sign-out-button";

export const metadata: Metadata = { title: "My children" };
export const dynamic = "force-dynamic";

/**
 * The parent's home: the children this school group lets them see.
 *
 * The list comes from `/portal/children`, which the backend filters per child on
 * the link's `can_view_results` -- a child the parent may only collect never
 * appears. The record shown is deliberately narrow (see `GuardianChildRead`): no
 * other guardian's contact details, no staff notes.
 */
export default async function ParentHomePage() {
  const guardian = await requireGuardian();
  const [t, children] = await Promise.all([
    getTranslations(),
    serverGet<GuardianChildRead[]>("/portal/children", [], "guardian"),
  ]);

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 w-full max-w-2xl items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-2">
            <LogoMark className="size-7 shrink-0" />
            <span className="truncate font-semibold">{guardian.organization_name}</span>
          </div>
          <div className="flex items-center gap-1">
            <LocaleSwitcher />
            <ParentSignOutButton />
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-2xl px-4 py-6">
        <p className="text-sm text-muted-foreground">{t.parent.portalName}</p>
        <h1 className="text-2xl font-semibold tracking-tight">{guardian.full_name}</h1>

        <h2 className="mt-6 mb-3 font-medium">{t.parent.myChildren}</h2>
        {children.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              {t.parent.noChildren}
            </CardContent>
          </Card>
        ) : (
          <ul className="grid gap-3">
            {children.map((child) => (
              <li key={child.student_id}>
                <Card>
                  <CardContent className="flex items-start gap-3 p-4">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-accent-foreground">
                      <GraduationCap className="size-5" aria-hidden />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{child.full_name}</p>
                      <p className="truncate text-sm text-muted-foreground">{child.school_name}</p>
                      <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <dt className="text-xs text-muted-foreground">{t.parent.admissionNo}</dt>
                          <dd>
                            {/* An inline LTR run, so the number reads left to right
                                but aligns with its label in an Urdu page. */}
                            <span dir="ltr" className="tabular-nums">
                              {child.admission_number}
                            </span>
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs text-muted-foreground">{t.parent.dateOfBirth}</dt>
                          <dd>{formatDate(child.date_of_birth)}</dd>
                        </div>
                      </dl>
                    </div>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        )}

        <p className="mt-6 text-center text-sm text-muted-foreground">{t.parent.moreSoon}</p>
      </main>
    </div>
  );
}
