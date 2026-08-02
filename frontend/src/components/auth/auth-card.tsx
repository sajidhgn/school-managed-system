import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

/**
 * The frame every auth screen sits in: login, signup, reset, invitation accept.
 *
 * A shared shell rather than per-page markup so the six of them cannot drift apart
 * in spacing, heading weight or footer placement — differences a user notices as
 * "this page feels different" without being able to say why.
 */
export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col justify-center px-4 py-16 sm:py-24">
      <div className="rounded-xl border border-border bg-card p-8 shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-1.5 text-sm text-muted-foreground text-pretty">{description}</p>
        ) : null}
        <div className="mt-6">{children}</div>
      </div>
      {footer ? (
        <p className="mt-5 text-center text-sm text-muted-foreground">{footer}</p>
      ) : null}
    </div>
  );
}

export function AuthLink({ href, children }: { href: Route; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-primary hover:underline">
      {children}
    </Link>
  );
}
