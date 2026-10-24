"use client";

import { AnimatePresence, motion } from "motion/react";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { EASE_OUT } from "@/components/marketing/motion/reveal";
import { NAV_ICONS, type NavIconName } from "@/components/marketing/nav/types";

/**
 * The home page's tour: one tab per part of the school office, each showing that
 * part's illustrated demo beside what it does. The panels are server-rendered and
 * handed in; this component only chooses which one is on screen.
 *
 * A WAI-ARIA tab list with automatic activation: arrow keys (mirrored in Urdu),
 * Home and End move between tabs.
 */
export function ProductTour({
  label,
  tabs,
}: {
  label: string;
  tabs: { id: string; label: string; icon: NavIconName; panel: ReactNode }[];
}) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const baseId = useId();
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  const select = (id: string) => {
    setActive(id);
    const node = buttons.current.get(id);
    node?.focus();
    node?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
  };

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.findIndex((tab) => tab.id === active);
    const rtl = document.documentElement.dir === "rtl";
    const forward = rtl ? "ArrowLeft" : "ArrowRight";
    const back = rtl ? "ArrowRight" : "ArrowLeft";
    let next = -1;
    if (event.key === forward) next = (index + 1) % tabs.length;
    else if (event.key === back) next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    event.preventDefault();
    select(tabs[next]!.id);
  };

  if (!current) return null;

  return (
    <div>
      <div role="tablist" aria-label={label} className="mk-tabs" onKeyDown={onKey}>
        {tabs.map((tab) => {
          const Icon = NAV_ICONS[tab.icon];
          const selected = tab.id === current.id;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                if (node) buttons.current.set(tab.id, node);
                else buttons.current.delete(tab.id);
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel`}
              tabIndex={selected ? 0 : -1}
              className="mk-tab"
              onClick={() => select(tab.id)}
            >
              {selected ? (
                <motion.span
                  layoutId={`${baseId}-pill`}
                  className="mk-tab__pill"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  aria-hidden
                />
              ) : null}
              <Icon className="relative size-4 shrink-0" aria-hidden />
              <span className="relative whitespace-nowrap">{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`${baseId}-panel`}
        aria-labelledby={`${baseId}-tab-${current.id}`}
        tabIndex={0}
        className="mt-10 rounded-[1.75rem] outline-none focus-visible:ring-2 focus-visible:ring-mk-ink"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={current.id}
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.38, ease: EASE_OUT }}
          >
            {current.panel}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
