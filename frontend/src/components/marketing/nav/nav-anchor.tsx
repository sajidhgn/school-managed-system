import type { Route } from "next";
import Link from "next/link";
import type { ComponentProps } from "react";

import type { NavLink } from "./types";

/** A menu link: the router for the site's own pages, a plain anchor for WhatsApp,
 * mail and phone links (which open in a new tab, apart from the dialler). */
export function NavAnchor({
  link,
  ...rest
}: { link: Pick<NavLink, "href" | "external"> } & Omit<ComponentProps<"a">, "href">) {
  if (link.external) {
    const newTab = !link.href.startsWith("tel:");
    return (
      <a
        href={link.href}
        {...(newTab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
        {...rest}
      />
    );
  }
  return <Link href={link.href as Route} {...rest} />;
}
