"use client";

import { AnimatePresence, motion, type Variants } from "motion/react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight, ChevronDown } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { cn } from "@/lib/utils";

import { NavAnchor } from "./nav-anchor";
import { NAV_ICONS, type NavEntry, type NavMenu } from "./types";

/**
 * The header's navigation from `lg` up: links, and menus that open on hover or
 * press into one shared panel.
 *
 * The panel is a single element that springs to each menu's width and height and
 * slides its contents toward the menu being opened, so moving along the bar feels
 * like one surface changing rather than boxes popping in and out.
 *
 * Keyboard: Enter, Space or ArrowDown opens a menu; Tab from an open trigger goes
 * into its panel and on past the last link to the next item; arrows move between
 * links; Escape closes and returns focus to the trigger.
 */

const WIDTHS: Record<NavMenu["width"], number> = { sm: 420, lg: 800 };

const SPRING = { type: "spring", stiffness: 380, damping: 34, mass: 0.9 } as const;

const SLIDE: Variants = {
  enter: (dir: number) => ({ opacity: 0, x: dir * 56 }),
  center: { opacity: 1, x: 0 },
  exit: (dir: number) => ({ opacity: 0, x: dir * -56 }),
};

export function MegaNav({ entries, label }: { entries: NavEntry[]; label: string }) {
  const menus = entries.flatMap((entry) => (entry.kind === "menu" ? [entry.menu] : []));
  const [open, setOpen] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [direction, setDirection] = useState(0);
  const [left, setLeft] = useState(0);
  const [height, setHeight] = useState<number | "auto">("auto");
  const last = useRef(-1);
  /** Opened by the mouse passing over it: a click then keeps it open, not closes it. */
  const byHover = useRef(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const navRef = useRef<HTMLElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const items = useRef(new Map<string, HTMLElement>());
  const pathname = usePathname();
  const pillId = useId();

  const menu = menus.find((m) => m.id === open) ?? null;
  const width = menu ? WIDTHS[menu.width] : 0;

  // Following a link (or the back button) closes the menu.
  useEffect(() => setOpen(null), [pathname]);

  const place = useCallback(
    (id: string) => {
      const nav = navRef.current;
      const trigger = items.current.get(id);
      const target = menus.find((m) => m.id === id);
      if (!nav || !trigger || !target) return;
      const navBox = nav.getBoundingClientRect();
      const box = trigger.getBoundingClientRect();
      const panel = Math.min(WIDTHS[target.width], window.innerWidth - 32);
      const centred = box.left + box.width / 2 - navBox.left - panel / 2;
      const min = 16 - navBox.left;
      const max = window.innerWidth - 16 - panel - navBox.left;
      setLeft(Math.max(min, Math.min(max, centred)));
    },
    [menus],
  );

  const show = (id: string) => {
    window.clearTimeout(closeTimer.current);
    const index = menus.findIndex((m) => m.id === id);
    const rtl = document.documentElement.dir === "rtl" ? -1 : 1;
    setDirection(last.current < 0 ? 0 : Math.sign(index - last.current) * rtl);
    last.current = index;
    place(id);
    setOpen(id);
  };

  const close = useCallback(() => {
    window.clearTimeout(closeTimer.current);
    last.current = -1;
    byHover.current = false;
    setOpen(null);
  }, []);

  const closeSoon = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(close, 180);
  };
  const keepOpen = () => window.clearTimeout(closeTimer.current);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!navRef.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      items.current.get(open)?.focus();
      close();
    };
    const onResize = () => place(open);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [open, close, place]);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  // The panel's height follows whichever menu's contents it holds.
  const [content, setContent] = useState<HTMLDivElement | null>(null);
  // Keeps the newest contents: the outgoing menu detaches after the new one attaches.
  const holdContent = useCallback((node: HTMLDivElement | null) => {
    if (node) setContent(node);
  }, []);
  useEffect(() => {
    if (!content) return;
    const observer = new ResizeObserver(() => setHeight(content.offsetHeight));
    observer.observe(content);
    return () => observer.disconnect();
  }, [content]);

  const links = () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>("a[href]") ?? []);
  const focusFirstLink = () => requestAnimationFrame(() => requestAnimationFrame(() => links()[0]?.focus()));

  /** The bar item after `id`, where Tab goes from a menu's last link. */
  const nextItem = (id: string) => {
    const index = entries.findIndex((e) => (e.kind === "menu" ? e.menu.id : e.id) === id);
    const next = entries[index + 1];
    return next ? items.current.get(next.kind === "menu" ? next.menu.id : next.id) : undefined;
  };

  const onTriggerKey = (id: string) => (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      show(id);
      focusFirstLink();
    } else if (event.key === "Tab" && !event.shiftKey && open === id) {
      event.preventDefault();
      focusFirstLink();
    }
  };

  const onPanelKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!open) return;
    const all = links();
    const i = all.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      all[(i + step + all.length) % all.length]?.focus();
    } else if (event.key === "Tab" && event.shiftKey && i === 0) {
      event.preventDefault();
      items.current.get(open)?.focus();
    } else if (event.key === "Tab" && !event.shiftKey && i === all.length - 1) {
      const next = nextItem(open);
      if (next) {
        event.preventDefault();
        next.focus();
      }
      close();
    }
  };

  const onBlur = (event: FocusEvent<HTMLElement>) => {
    if (!navRef.current?.contains(event.relatedTarget as Node | null)) close();
  };

  const pill = hovered ?? open;

  return (
    <nav
      ref={navRef}
      aria-label={label}
      className="relative hidden lg:block"
      onPointerLeave={() => {
        setHovered(null);
        if (open) closeSoon();
      }}
      onPointerEnter={keepOpen}
      onBlur={onBlur}
    >
      <ul className="flex items-center gap-0.5">
        {entries.map((entry) => {
          const id = entry.kind === "menu" ? entry.menu.id : entry.id;
          const register = (node: HTMLElement | null) => {
            if (node) items.current.set(id, node);
            else items.current.delete(id);
          };
          const highlight =
            pill === id ? (
              <motion.span layoutId={pillId} className="mk-nav__pill" transition={SPRING} aria-hidden />
            ) : null;

          if (entry.kind === "link") {
            const current = pathname === entry.href;
            return (
              <li key={id} onPointerEnter={() => setHovered(id)}>
                <Link
                  ref={register}
                  href={entry.href as Route}
                  className="mk-nav__item"
                  aria-current={current ? "page" : undefined}
                  onPointerEnter={() => open && closeSoon()}
                >
                  {highlight}
                  <span className="relative">{entry.label}</span>
                </Link>
              </li>
            );
          }

          const expanded = open === id;
          return (
            <li key={id} onPointerEnter={() => setHovered(id)}>
              <button
                ref={register}
                type="button"
                className="mk-nav__item"
                aria-expanded={expanded}
                aria-controls={expanded ? `mk-menu-${id}` : undefined}
                onPointerEnter={(event) => {
                  if (event.pointerType !== "mouse" || expanded) return;
                  byHover.current = true;
                  show(id);
                }}
                onClick={() => {
                  if (expanded && byHover.current) byHover.current = false;
                  else if (expanded) close();
                  else show(id);
                }}
                onKeyDown={onTriggerKey(id)}
              >
                {highlight}
                <span className="relative">{entry.menu.label}</span>
                <motion.span
                  className="relative inline-flex"
                  animate={{ rotate: expanded ? 180 : 0 }}
                  transition={SPRING}
                  aria-hidden
                >
                  <ChevronDown className="size-3.5 opacity-70" />
                </motion.span>
              </button>
            </li>
          );
        })}
      </ul>

      <AnimatePresence>
        {menu ? (
          <motion.div
            key="mk-mega"
            ref={panelRef}
            id={`mk-menu-${menu.id}`}
            className="mk-mega mk-heroui"
            initial={{ opacity: 0, y: 12, scale: 0.97, left, width }}
            animate={{ opacity: 1, y: 0, scale: 1, left, width }}
            exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.16 } }}
            transition={SPRING}
            onPointerEnter={keepOpen}
            onKeyDown={onPanelKey}
          >
            <motion.div className="relative overflow-hidden" animate={{ height }} transition={SPRING}>
              <AnimatePresence initial={false} custom={direction} mode="popLayout">
                <motion.div
                  key={menu.id}
                  ref={holdContent}
                  custom={direction}
                  variants={SLIDE}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  transition={{ ...SPRING, opacity: { duration: 0.18 } }}
                >
                  <MenuPanel menu={menu} onNavigate={close} />
                </motion.div>
              </AnimatePresence>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </nav>
  );
}

function MenuPanel({ menu, onNavigate }: { menu: NavMenu; onNavigate: () => void }) {
  const [lit, setLit] = useState<string | null>(null);
  const litId = useId();

  return (
    <div className="mk-mega__body">
      <div
        className={cn(
          "grid gap-x-4 gap-y-6",
          menu.groups.length > 1 && "grid-cols-2",
          menu.feature && "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_15rem]",
        )}
        onPointerLeave={() => setLit(null)}
      >
        {menu.groups.map((group) => (
          <div key={group.title}>
            <p className="mk-mega__title">{group.title}</p>
            <ul className="mt-2 grid gap-0.5">
              {group.links.map((link) => {
                const Icon = NAV_ICONS[link.icon];
                return (
                  <li key={link.href}>
                    <NavAnchor
                      link={link}
                      className="mk-mega__link"
                      onClick={onNavigate}
                      onPointerEnter={() => setLit(link.href)}
                      onFocus={() => setLit(link.href)}
                    >
                      {lit === link.href ? (
                        <motion.span
                          layoutId={litId}
                          className="mk-mega__lit"
                          transition={{ type: "spring", stiffness: 520, damping: 40 }}
                          aria-hidden
                        />
                      ) : null}
                      <span className="mk-mega__icon">
                        <Icon className="size-4.5" aria-hidden />
                      </span>
                      <span className="relative min-w-0">
                        <span className="mk-mega__label">{link.label}</span>
                        {link.body ? <span className="mk-mega__text">{link.body}</span> : null}
                      </span>
                    </NavAnchor>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}

        {menu.feature ? (
          <Link href={menu.feature.href as Route} className="mk-mega__feature mk-night" onClick={onNavigate}>
            <span className="mk-mega__feature-glow" aria-hidden />
            <span className="relative font-mk-display text-lg leading-snug font-bold">{menu.feature.title}</span>
            <span className="relative mt-2 text-sm leading-relaxed text-mk-muted">{menu.feature.body}</span>
            <span className="relative mt-auto inline-flex items-center gap-1.5 pt-5 text-sm font-semibold text-mk-ink">
              {menu.feature.cta}
              <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
            </span>
          </Link>
        ) : null}
      </div>

      {menu.footer ? (
        <div className="mk-mega__footer">
          <p className="text-mk-muted">{menu.footer.text}</p>
          <Link href={menu.footer.href as Route} className="mk-textlink shrink-0 text-sm" onClick={onNavigate}>
            {menu.footer.label}
            <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
          </Link>
        </div>
      ) : null}
    </div>
  );
}
