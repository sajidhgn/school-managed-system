"use client";

import { RouterProvider } from "@heroui/react";
import { MotionConfig } from "motion/react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { UNSAFE_PortalProvider } from "react-aria";

/** The element HeroUI's menus and drawers render into; the layout places it. */
export const OVERLAY_ROOT_ID = "mk-overlays";

/**
 * What HeroUI needs around the public site.
 *
 * Its links (breadcrumbs, menu items) navigate through Next's router, not with a
 * full page load. Its overlays render into #mk-overlays rather than <body>: that
 * element sits inside `.mk` and carries `.mk-heroui`, so a menu gets the site's
 * fonts and HeroUI's variables, which are scoped rather than global (heroui.css).
 *
 * Motion follows the visitor's reduced-motion setting everywhere on the site:
 * with it on, elements still fade in, but nothing slides, tilts or floats.
 */
export function HeroUIScope({ children }: { children: ReactNode }) {
  const router = useRouter();

  return (
    <RouterProvider navigate={(href) => router.push(href as Route)}>
      <UNSAFE_PortalProvider getContainer={() => document.getElementById(OVERLAY_ROOT_ID)}>
        <MotionConfig reducedMotion="user">{children}</MotionConfig>
      </UNSAFE_PortalProvider>
    </RouterProvider>
  );
}
