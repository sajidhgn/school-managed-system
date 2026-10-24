"use client";

import { Button, Drawer, useOverlayState } from "@heroui/react";
import { AnimatePresence, motion } from "motion/react";
import type { Route } from "next";
import Link from "next/link";
import { ChevronDown, Menu } from "lucide-react";
import { useId, useState, type MouseEvent, type ReactNode } from "react";

import { NavAnchor } from "@/components/marketing/nav/nav-anchor";
import { NAV_ICONS, type NavEntry } from "@/components/marketing/nav/types";

/**
 * The public site's navigation below `lg`: a HeroUI drawer from the inline-end
 * edge, the side the menu button is on, holding the same menus as the desktop
 * bar as sections that open one at a time. The layout (and an open drawer)
 * survives client-side navigation, so following any link in it closes it.
 *
 * `placement="right"` is already the inline end in Urdu: HeroUI places the panel
 * with `justify-end`. Only its slide is physical; marketing.css mirrors it.
 */
export function MobileMenu({
  label,
  entries,
  actions,
  children,
}: {
  label: string;
  entries: NavEntry[];
  /** The sign-in and start buttons, pinned to the foot of the drawer. */
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const state = useOverlayState();
  const [section, setSection] = useState<string | null>(null);
  const baseId = useId();

  const closeOnLink = (event: MouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest("a")) state.close();
  };

  return (
    <Drawer state={state}>
      <Button isIconOnly variant="outline" size="sm" aria-label={label} className="lg:hidden">
        <Menu className="size-4" aria-hidden />
      </Button>
      <Drawer.Backdrop>
        <Drawer.Content placement="right" className="lg:hidden">
          <Drawer.Dialog aria-label={label}>
            <Drawer.CloseTrigger />
            <Drawer.Body className="flex flex-col pt-12" onClick={closeOnLink}>
              <nav aria-label="Site">
                <ul className="grid gap-0.5">
                  {entries.map((entry, i) => (
                    <motion.li
                      key={entry.kind === "menu" ? entry.menu.id : entry.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.06 * i + 0.08, type: "spring", stiffness: 340, damping: 30 }}
                    >
                      {entry.kind === "link" ? (
                        <Link href={entry.href as Route} className="mk-drawer__item">
                          {entry.label}
                        </Link>
                      ) : (
                        <Section
                          id={`${baseId}-${entry.menu.id}`}
                          entry={entry}
                          open={section === entry.menu.id}
                          onToggle={() => setSection(section === entry.menu.id ? null : entry.menu.id)}
                        />
                      )}
                    </motion.li>
                  ))}
                </ul>
              </nav>
              {actions ? <div className="mt-6 grid gap-2">{actions}</div> : null}
              {children ? <div className="mt-6 border-t border-mk-line px-3 pt-4">{children}</div> : null}
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}

function Section({
  id,
  entry,
  open,
  onToggle,
}: {
  id: string;
  entry: Extract<NavEntry, { kind: "menu" }>;
  open: boolean;
  onToggle: () => void;
}) {
  const links = entry.menu.groups.flatMap((group) => group.links);
  return (
    <>
      <button type="button" className="mk-drawer__item w-full" aria-expanded={open} aria-controls={id} onClick={onToggle}>
        {entry.menu.label}
        <motion.span className="ms-auto inline-flex" animate={{ rotate: open ? 180 : 0 }} aria-hidden>
          <ChevronDown className="size-4 opacity-70" />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.ul
            id={id}
            className="grid overflow-hidden ps-2"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
          >
            {links.map((link) => {
              const Icon = NAV_ICONS[link.icon];
              return (
                <li key={link.href}>
                  <NavAnchor link={link} className="mk-drawer__link">
                    <span className="mk-mega__icon">
                      <Icon className="size-4" aria-hidden />
                    </span>
                    {link.label}
                  </NavAnchor>
                </li>
              );
            })}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </>
  );
}
