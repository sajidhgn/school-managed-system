import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AskLibraryView } from "./ask-view";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { booksMessages } from "@/lib/i18n/modules/books";
import { getCatalog } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getCatalog(booksMessages)).meta.ask };
}

export const dynamic = "force-dynamic";

/**
 * Questions and passage search across every book this campus can see.
 *
 * `book:read` is enough: asking reads the books, it changes nothing. A teacher is
 * bounded to their own classes' books by the server, not by this page.
 */
export default async function AskLibraryPage() {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.bookRead)) redirect("/dashboard");

  return (
    // The view reads `?book=` (from a book's page) out of the query string.
    <Suspense>
      <AskLibraryView />
    </Suspense>
  );
}
