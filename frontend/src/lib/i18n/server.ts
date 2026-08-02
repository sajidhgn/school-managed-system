import "server-only";

import { cookies } from "next/headers";

import { DEFAULT_LOCALE, LOCALE_COOKIE, isLocale, type Locale } from "./config";
import { getMessages, type Messages } from "./messages";

/**
 * Resolve the active locale on the server.
 *
 * Cookie-based rather than path-based (`/en/...`, `/ur/...`). A path segment is the
 * more conventional choice and gives each locale its own URL, which is better for a
 * public marketing site — but it also doubles every route, complicates the three
 * route groups the spec defines, and makes every internal link locale-aware.
 *
 * For an authenticated admin panel, where the audience is staff who set their
 * language once, a cookie is the right trade. If the marketing pages later need
 * indexable per-locale URLs, the switch is confined to this file plus a rewrite in
 * middleware — the components already read their strings through `t`.
 *
 * Falls back to the default on an unrecognised value: a hand-edited cookie must not
 * be able to crash a server render.
 */
export async function getLocale(): Promise<Locale> {
  const cookie = (await cookies()).get(LOCALE_COOKIE)?.value;
  return isLocale(cookie) ? cookie : DEFAULT_LOCALE;
}

export async function getTranslations(): Promise<Messages> {
  return getMessages(await getLocale());
}
