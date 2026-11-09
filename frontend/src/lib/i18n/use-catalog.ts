"use client";

import { useTranslations } from "@/components/providers/i18n-provider";

import { pickCatalog, type Catalog, type Translation } from "./catalog";

/** A module catalog's strings in the viewer's language. See `catalog.ts`. */
export function useCatalog<T>(catalog: Catalog<T>): Translation<T> {
  const { locale } = useTranslations();
  return pickCatalog(catalog, locale);
}
