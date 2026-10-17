import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { BooksView } from "./books-view";

export const metadata: Metadata = { title: "Books" };
export const dynamic = "force-dynamic";

/**
 * The campus's textbook library. Books belong to one campus's classes, hence
 * `requireSchoolContext()`; who may change WHICH book is decided per book by the
 * server and arrives as `can_edit`.
 */
export default async function BooksPage() {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.bookRead)) redirect("/dashboard");

  return (
    <BooksView
      canWrite={
        hasPermission(user, PERMISSIONS.bookWrite) || hasPermission(user, PERMISSIONS.bookManage)
      }
    />
  );
}
