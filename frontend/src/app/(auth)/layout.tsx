import Link from "next/link";
import { School } from "lucide-react";

/**
 * Split auth layout: form on the left, product framing on the right.
 * The right panel is decorative and hidden below `lg` — nothing essential
 * lives there.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="flex flex-col px-6 py-10 sm:px-10">
        <Link href="/login" className="mb-10 inline-flex items-center gap-2 self-start">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <School className="size-4" />
          </div>
          <span className="text-sm font-semibold">School Management</span>
        </Link>

        <main id="main" className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">{children}</div>
        </main>
      </div>

      <aside
        aria-hidden
        className="relative hidden overflow-hidden border-l border-border bg-accent/40 lg:block"
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,var(--primary)/0.12,transparent_55%)]" />
        <div className="relative flex h-full flex-col justify-center px-14">
          <blockquote className="max-w-md space-y-5">
            <p className="text-2xl font-semibold leading-snug tracking-tight text-balance">
              Every student, class, and admission — in one place.
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Multi-tenant by design. Each school's data is isolated at the database level,
              so records never cross institutional boundaries.
            </p>
          </blockquote>
        </div>
      </aside>
    </div>
  );
}
