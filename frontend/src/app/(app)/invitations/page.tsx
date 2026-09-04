import { redirect } from "next/navigation";

/**
 * Invitations now live on the Members page as a collapsible section. This route
 * survives only so old links and bookmarks keep working; `?invite=1` opens that
 * section on arrival.
 */
export default function InvitationsPage() {
  redirect("/members?invite=1");
}
