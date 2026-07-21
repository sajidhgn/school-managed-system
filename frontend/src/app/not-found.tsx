import Link from "next/link";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Rendered outside every route group, so it cannot rely on the dashboard shell
 * or on there being a signed-in user.
 */
export default function NotFound() {
  return (
    <main
      id="main"
      className="flex min-h-svh flex-col items-center justify-center gap-5 px-6 text-center"
    >
      <div className="flex size-12 items-center justify-center rounded-full bg-muted">
        <Compass className="size-5 text-muted-foreground" />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium text-muted-foreground">404</p>
        <h1 className="text-2xl font-semibold tracking-tight">This page doesn&apos;t exist</h1>
        <p className="mx-auto max-w-sm text-sm leading-relaxed text-muted-foreground">
          The link may be out of date, or the page may have been moved.
        </p>
      </div>

      <Button asChild>
        <Link href="/dashboard">Back to dashboard</Link>
      </Button>
    </main>
  );
}
