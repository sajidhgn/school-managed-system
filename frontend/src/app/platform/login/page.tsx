import type { Metadata } from "next";
import { Suspense } from "react";

import { PlatformLoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Operator sign-in.
 *
 * A separate login from the tenant one, against a separate table, writing a separate
 * cookie pair. There is deliberately no "create account", no "forgot password" and
 * no link back into the marketing site: operator accounts are seeded by the CLI and
 * their credentials rotate through it.
 *
 * An emailed password reset for a role that can read every school's records would
 * reduce the platform's security to the security of one inbox.
 */
export default function PlatformLoginPage() {
  return (
    <div className="grid min-h-svh place-items-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2 text-slate-100">
          <span className="grid size-7 place-items-center rounded-lg bg-slate-100 text-sm font-bold text-slate-950">
            E
          </span>
          <span className="font-semibold">Operator console</span>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h1 className="text-lg font-semibold text-slate-100">Sign in</h1>
          <p className="mt-1 text-sm text-slate-400">
            Platform operators only. Accounts are provisioned by the seed CLI.
          </p>
          <div className="mt-6">
            {/* The form reads `?next=` via useSearchParams, which needs a Suspense
                boundary or Next.js opts the whole route out of static rendering. */}
            <Suspense fallback={null}>
              <PlatformLoginForm />
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
}
