import { permanentRedirect } from "next/navigation";

/**
 * The metrics page grew into the dashboard at `/platform`, which shows the same
 * figures plus growth, revenue and watch lists. Kept as a redirect so bookmarks and
 * old links still land somewhere useful.
 */
export default function MetricsPage() {
  permanentRedirect("/platform");
}
