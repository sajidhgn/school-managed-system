"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { Locale } from "@/lib/i18n/config";
import type { Messages } from "@/lib/i18n/messages";

/**
 * Makes the active locale's strings available to client components.
 *
 * The catalog is resolved on the server (from a cookie) and passed down, so there is
 * no loading state and no flash of untranslated text. Client components read strings
 * with `useTranslations()`; server components call `getTranslations()` directly.
 */

interface I18nValue {
  locale: Locale;
  dir: "ltr" | "rtl";
  t: Messages;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({
  locale,
  dir,
  messages,
  children,
}: {
  locale: Locale;
  dir: "ltr" | "rtl";
  messages: Messages;
  children: ReactNode;
}) {
  return (
    <I18nContext.Provider value={{ locale, dir, t: messages }}>{children}</I18nContext.Provider>
  );
}

export function useTranslations(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useTranslations() was called outside <I18nProvider>.");
  }
  return value;
}
