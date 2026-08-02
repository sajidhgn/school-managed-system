import Link from "next/link";
import { Building2, KeyRound, Receipt, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getTranslations } from "@/lib/i18n/server";

export default async function LandingPage() {
  const t = await getTranslations();

  const pillars = [
    {
      icon: Building2,
      title: "Every campus, one account",
      body: "Add schools as the group grows. Staff, students and settings stay scoped to the campus they belong to.",
    },
    {
      icon: ShieldCheck,
      title: "Separation you can point to",
      body: "Each organization's data is isolated by the database itself, not by a filter someone remembered to write.",
    },
    {
      icon: KeyRound,
      title: "Roles that fit your school",
      body: "Start from Principal, Teacher and Accountant, then build the roles you actually use. Revoking access takes effect immediately.",
    },
    {
      icon: Receipt,
      title: "Billing that never holds records hostage",
      body: "A payment problem makes the panel read-only. Your students' records stay readable and exportable, always.",
    },
  ];

  return (
    <>
      <section className="mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <div className="max-w-2xl">
          <p className="mb-4 inline-flex items-center rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
            Built for school groups
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            {t.marketing.heroTitle}
          </h1>
          <p className="mt-5 text-lg leading-relaxed text-muted-foreground text-pretty">
            {t.marketing.heroSubtitle}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg">
              <Link href="/signup">{t.marketing.heroCta}</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/pricing">{t.marketing.heroSecondary}</Link>
            </Button>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Free for one school and 50 students. No card required.
          </p>
        </div>
      </section>

      <section className="border-t border-border/70 bg-card/40">
        <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-16 sm:grid-cols-2 sm:px-6">
          {pillars.map(({ icon: Icon, title, body }) => (
            <div key={title} className="flex gap-4">
              <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
                <Icon className="size-5" aria-hidden />
              </div>
              <div>
                <h2 className="font-medium">{title}</h2>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground text-pretty">
                  {body}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto w-full max-w-6xl px-4 py-20 text-center sm:px-6">
        <h2 className="text-2xl font-semibold tracking-tight">Ready when you are</h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Create your organization, add your first school, and invite your staff. It takes a few
          minutes.
        </p>
        <Button asChild size="lg" className="mt-7">
          <Link href="/signup">{t.marketing.heroCta}</Link>
        </Button>
      </section>
    </>
  );
}
