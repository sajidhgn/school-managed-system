"use client";

import { Breadcrumbs as HeroBreadcrumbs } from "@heroui/react";
import type { Route } from "next";
import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";

/**
 * Visible breadcrumb trail, HeroUI's. The last item has no link and is marked as
 * the current page. The matching BreadcrumbList JSON-LD is on the page.
 *
 * A client module: `@heroui/react` cannot be imported from a server component.
 */
export function Breadcrumbs({ items }: { items: { href?: Route; label: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mk-rise mb-8" style={{ "--i": 0 } as CSSProperties}>
      <HeroBreadcrumbs separator={<ChevronRight className="size-3.5 text-mk-muted rtl:-scale-x-100" aria-hidden />}>
        {items.map((item) => (
          <HeroBreadcrumbs.Item key={item.label} href={item.href}>
            {item.label}
          </HeroBreadcrumbs.Item>
        ))}
      </HeroBreadcrumbs>
    </nav>
  );
}
