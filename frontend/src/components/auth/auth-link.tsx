import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

/** A link under an auth form ("Sign up", "Forgot password?"). Its own module so the
 * client-side forms can use it without pulling in AuthCard, which reads the locale
 * on the server. */
export function AuthLink({ href, children }: { href: Route; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-primary hover:underline">
      {children}
    </Link>
  );
}
