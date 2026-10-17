import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireSchoolContext } from "@/lib/auth/session";
import { BookDetailView } from "./book-detail-view";

export const metadata: Metadata = { title: "Book" };
export const dynamic = "force-dynamic";

/** One book: its chapter list, each chapter's uploads, the agent's report, and search. */
export default async function BookPage({ params }: { params: Promise<{ bookId: string }> }) {
  const { user } = await requireSchoolContext();
  if (!hasPermission(user, PERMISSIONS.bookRead)) redirect("/dashboard");
  const { bookId } = await params;
  return <BookDetailView bookId={bookId} />;
}
