"use client";

import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import {
  CalendarCheck,
  FileText,
  GraduationCap,
  LayoutDashboard,
  MessageCircle,
  Receipt,
  Search,
  Timer,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";

import type { MarketingCopy } from "@/components/marketing/copy";
import { LogoMark } from "@/components/marketing/logo";
import { EASE_OUT } from "@/components/marketing/motion/reveal";

/**
 * The home hero's illustration: a SchoolYar dashboard in a browser window, tilted
 * toward the headline and following the pointer, with the month's fee chart
 * growing, today's register filling in, a feed of what the school just did, and
 * three notes floating off its edges.
 *
 * It is a picture, so it is hidden from assistive technology and described in
 * words instead. Its figures are an example; the description says so.
 *
 * The feed moves through its items twice and then rests, so nothing on the page
 * keeps moving on its own for long.
 */

type Copy = MarketingCopy["home"]["dashboard"];

const SIDE_ICONS = [LayoutDashboard, Users, Receipt, CalendarCheck, GraduationCap, MessageCircle, FileText];
const FEED_ICONS = [Receipt, MessageCircle, CalendarCheck, FileText, Timer];
const CALLOUT_ICONS = [MessageCircle, Receipt, CalendarCheck];

/** Six months of paid challans, as a share of each month's total. */
const BARS = [58, 66, 63, 74, 70, 86];
/** Present, absent, late: percentages of the day's register. */
const SPLIT = [94, 4, 2];

const FEED_SIZE = 3;
const FEED_EVERY_MS = 2600;

export function HeroDashboard({ copy }: { copy: Copy }) {
  const reduce = useReducedMotion();
  const direction = useRef(1);
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const sx = useSpring(px, { stiffness: 110, damping: 18 });
  const sy = useSpring(py, { stiffness: 110, damping: 18 });
  // At rest the window leans toward the headline; the pointer moves it ±5°.
  const rotateY = useTransform(sx, (v) => (reduce ? 0 : ((v - 0.5) * 10 - 9) * direction.current));
  const rotateX = useTransform(sy, (v) => (reduce ? 0 : (0.5 - v) * 8 + 5));

  useEffect(() => {
    direction.current = document.documentElement.dir === "rtl" ? -1 : 1;
    px.set(0.5001);
  }, [px]);

  const track = (event: PointerEvent<HTMLDivElement>) => {
    if (reduce || event.pointerType !== "mouse") return;
    const box = event.currentTarget.getBoundingClientRect();
    px.set((event.clientX - box.left) / box.width);
    py.set((event.clientY - box.top) / box.height);
  };
  const rest = () => {
    px.set(0.5);
    py.set(0.5);
  };

  return (
    // `mk-ur-deco` opts the mock out of the site's tall Urdu line height
    // (marketing.css); site.css gives it one of its own.
    <div className="mk-dash-wrap mk-ur-deco" onPointerMove={track} onPointerLeave={rest}>
      <p className="sr-only">{copy.description}</p>

      <motion.div
        className="mk-dash"
        style={{ rotateX, rotateY }}
        initial={{ opacity: 0, y: 48 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1, ease: EASE_OUT, delay: 0.25 }}
        aria-hidden
      >
        <div className="mk-dash__bar">
          <span className="mk-dash__dots">
            <i />
            <i />
            <i />
          </span>
          <span className="mk-dash__search">
            <Search className="size-3" />
            <span className="truncate">{copy.search}</span>
          </span>
          <span className="mk-dash__avatar" />
        </div>

        <div className="mk-dash__body">
          <aside className="mk-dash__side">
            <span className="mk-dash__logo">
              <LogoMark className="size-5" />
            </span>
            {copy.nav.map((item, i) => {
              const Icon = SIDE_ICONS[i] ?? LayoutDashboard;
              return (
                <span key={item} className="mk-dash__nav" data-active={i === 0 ? "" : undefined}>
                  <Icon className="size-3.5 shrink-0" />
                  <span className="truncate">{item}</span>
                </span>
              );
            })}
          </aside>

          <div className="mk-dash__main">
            <div className="flex items-end justify-between gap-3">
              <div className="min-w-0">
                <p className="mk-dash__muted">{copy.greeting}</p>
                <p className="mk-dash__title truncate">{copy.campus}</p>
              </div>
              <span className="mk-dash__live">
                <span className="mk-dash__pulse" />
                {copy.activityTitle}
              </span>
            </div>

            <div className="mk-dash__kpis">
              {copy.kpis.map(([label, value, note], i) => (
                <motion.div
                  key={label}
                  className="mk-dash__card mk-dash__kpi"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, ease: EASE_OUT, delay: 0.55 + i * 0.08 }}
                >
                  <span className="mk-dash__muted truncate">{label}</span>
                  <span className="mk-dash__value">{value}</span>
                  <span className="mk-dash__note truncate">{note}</span>
                </motion.div>
              ))}
            </div>

            <div className="mk-dash__row">
              <div className="mk-dash__card">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="mk-dash__label">{copy.chartTitle}</span>
                  <span className="mk-dash__note truncate">{copy.chartNote}</span>
                </div>
                <div className="mk-dash__bars">
                  {BARS.map((height, i) => (
                    <span key={i} className="mk-dash__barcol">
                      <span className="mk-dash__track">
                        <motion.span
                          className="mk-dash__barfill"
                          data-last={i === BARS.length - 1 ? "" : undefined}
                          style={{ height: `${height}%`, originY: 1 }}
                          initial={{ scaleY: 0 }}
                          animate={{ scaleY: 1 }}
                          transition={{ duration: 0.9, ease: EASE_OUT, delay: 0.8 + i * 0.09 }}
                        />
                      </span>
                      <span className="mk-dash__note">{copy.months[i]}</span>
                    </span>
                  ))}
                </div>
              </div>

              <div className="mk-dash__card mk-dash__today">
                <span className="mk-dash__label">{copy.todayTitle}</span>
                <Donut />
                <ul className="mk-dash__legend">
                  {copy.legend.map((name, i) => (
                    <li key={name}>
                      <i data-tone={i} />
                      <span className="truncate">{name}</span>
                      <b>{SPLIT[i]}%</b>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <Feed copy={copy} still={Boolean(reduce)} />
          </div>
        </div>
      </motion.div>

      {copy.callouts.map(([title, body], i) => {
        const Icon = CALLOUT_ICONS[i] ?? MessageCircle;
        return (
          <motion.div
            key={title}
            className="mk-callout"
            data-at={i}
            initial={{ opacity: 0, y: 16, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: "spring", stiffness: 260, damping: 20, delay: 1.3 + i * 0.55 }}
            aria-hidden
          >
            <motion.div
              className="mk-callout__inner"
              animate={{ y: [0, -7, 0] }}
              transition={{ duration: 4 + i * 0.8, repeat: 3, ease: "easeInOut", delay: 2 + i * 0.55 }}
            >
              <span className="mk-callout__icon">
                <Icon className="size-4" />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[0.8rem] font-semibold">{title}</span>
                <span className="block truncate text-[0.72rem] text-mk-muted">{body}</span>
              </span>
            </motion.div>
          </motion.div>
        );
      })}
    </div>
  );
}

/** Today's register as a ring: present, absent and late, drawn in turn. */
function Donut() {
  const radius = 15.9155; // a circumference of 100, so lengths are percentages
  let start = 0;
  return (
    <svg viewBox="0 0 42 42" className="mk-dash__donut">
      <circle cx="21" cy="21" r={radius} className="mk-dash__ring" />
      {SPLIT.map((share, i) => {
        const offset = start;
        start += share;
        return (
          <motion.circle
            key={i}
            cx="21"
            cy="21"
            r={radius}
            data-tone={i}
            className="mk-dash__arc"
            style={{ rotate: offset * 3.6 - 90, originX: "50%", originY: "50%" }}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: Math.max(share - 0.6, 0.4) / 100 }}
            transition={{ duration: 1.1, ease: EASE_OUT, delay: 1 + i * 0.35 }}
          />
        );
      })}
      <text x="21" y="23.5" textAnchor="middle" className="mk-dash__donut-text">
        {SPLIT[0]}%
      </text>
    </svg>
  );
}

/** What the school just did, newest first; a new line arrives every few seconds. */
function Feed({ copy, still }: { copy: Copy; still: boolean }) {
  const total = copy.activity.length;
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (still) return;
    let count = 0;
    const timer = window.setInterval(() => {
      count += 1;
      setTick((t) => t + 1);
      if (count >= total * 2) window.clearInterval(timer);
    }, FEED_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [still, total]);

  const first = (((-tick % total) + total) % total) as number;
  const rows = Array.from({ length: FEED_SIZE }, (_, slot) => (first + slot) % total);

  return (
    <div className="mk-dash__card">
      <span className="mk-dash__label">{copy.activityTitle}</span>
      <ul className="mk-dash__feed">
        <AnimatePresence initial={false} mode="popLayout">
          {rows.map((index, slot) => {
            const Icon = FEED_ICONS[index] ?? Receipt;
            return (
              <motion.li
                key={index}
                layout
                initial={{ opacity: 0, y: -14, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10 }}
                transition={{ type: "spring", stiffness: 300, damping: 28 }}
              >
                <span className="mk-dash__feed-icon">
                  <Icon className="size-3" />
                </span>
                <span className="min-w-0 flex-1 truncate">{copy.activity[index]?.[0]}</span>
                <span className="mk-dash__note shrink-0">{copy.activity[slot]?.[1]}</span>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </div>
  );
}
