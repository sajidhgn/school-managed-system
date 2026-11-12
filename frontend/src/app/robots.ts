import type { MetadataRoute } from "next";

import { SITE_NOINDEX, absoluteUrl } from "@/lib/site";

/**
 * /robots.txt. Crawlers may read the public site; everything behind a login is
 * listed so they do not waste their visit on redirects to /login.
 *
 * This is a courtesy to crawlers, not access control: the paths stay protected by
 * middleware and the backend whether or not a robot obeys this file.
 */

// The tenant panel's top-level routes, from src/app/(app). A route group adds no
// URL prefix, so each one is listed.
const APP_ROUTES = [
  "/academic-years",
  "/attendance",
  "/audit",
  "/billing",
  "/books",
  "/classes",
  "/dashboard",
  "/exams",
  "/fees",
  "/invitations",
  "/members",
  "/onboarding",
  "/papers",
  "/roles",
  "/schools",
  "/select-school",
  "/settings",
  "/students",
  "/subjects",
  "/whatsapp",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/api/",
        "/platform",
        "/invite/",
        "/reset-password",
        "/verify-email",
        ...APP_ROUTES,
      ],
    },
    // With SITE_NOINDEX the public pages stay crawlable on purpose: a crawler only
    // obeys the noindex tag and header on a page it is allowed to fetch, so a
    // blanket `Disallow: /` would leave bare URLs indexable from outside links.
    ...(SITE_NOINDEX ? {} : { sitemap: absoluteUrl("/sitemap.xml") }),
  };
}
