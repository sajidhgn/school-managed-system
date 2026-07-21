import { redirect } from "next/navigation";

/**
 * The app has no marketing landing page — "/" is just a doorway. Middleware
 * bounces unauthenticated visitors from /dashboard to /login, so this redirect
 * is correct for signed-in and signed-out visitors alike.
 */
export default function RootPage() {
  redirect("/dashboard");
}
