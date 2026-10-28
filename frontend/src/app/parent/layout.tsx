import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Parent portal", template: "%s · Parent portal" },
  // Nothing here is for search engines: every page but sign-in needs a session.
  robots: { index: false, follow: false },
};

/**
 * The parent portal: phone and WhatsApp code in, a parent's own children out.
 *
 * A pass-through, like the platform console's: `/parent/login` needs no chrome, and
 * the signed-in pages draw their own header after resolving the parent.
 */
export default function ParentLayout({ children }: { children: React.ReactNode }) {
  return children;
}
