"use client";

import { motion, useReducedMotion, type Variants } from "motion/react";
import { useRef } from "react";
import {
  CalendarCheck,
  ClipboardList,
  FileText,
  GraduationCap,
  IdCard,
  MessageCircle,
  Receipt,
  Users,
} from "lucide-react";

import { LogoMark } from "@/components/marketing/logo";
import { EASE_OUT, useRevealed } from "@/components/marketing/motion/reveal";

/**
 * SchoolYar at the centre of the modules it joins up: spokes draw out to each one
 * as the diagram scrolls into view, and points of light run along them into the
 * middle, the way every module writes to the same list of students and staff.
 *
 * Decorative: the section's text says the same in words.
 */

/** The icons for `home.security.hub`, in its order. */
const ICONS = [Users, Receipt, CalendarCheck, GraduationCap, FileText, MessageCircle, ClipboardList, IdCard];

const RADIUS = 39;

/** Everything waits for the diagram as a whole to come on screen (held as a
 * state, so pieces that remount after a language switch still appear); `custom`
 * is each piece's position in the sequence. */
const SPOKE: Variants = {
  hidden: { pathLength: 0, opacity: 0 },
  show: (i: number) => ({
    pathLength: 1,
    opacity: 1,
    transition: { duration: 0.8, ease: EASE_OUT, delay: 0.2 + i * 0.07 },
  }),
};

const CORE: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  show: { opacity: 1, scale: 1, transition: { type: "spring", stiffness: 200, damping: 18 } },
};

const NODE: Variants = {
  hidden: { opacity: 0, scale: 0.6 },
  show: (i: number) => ({
    opacity: 1,
    scale: 1,
    transition: { type: "spring", stiffness: 260, damping: 20, delay: 0.45 + i * 0.07 },
  }),
};

export function ModuleHub({ name, nodes }: { name: string; nodes: string[] }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const shown = useRevealed(ref);
  const points = nodes.map((label, i) => {
    const angle = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
    return { label, x: 50 + RADIUS * Math.cos(angle), y: 50 + RADIUS * Math.sin(angle) };
  });

  return (
    <motion.div ref={ref} className="mk-hub" initial="hidden" animate={shown ? "show" : "hidden"} aria-hidden>
      <svg viewBox="0 0 100 100" className="absolute inset-0 size-full overflow-visible">
        <circle cx="50" cy="50" r={RADIUS} className="mk-hub__orbit" />
        <circle cx="50" cy="50" r="24" className="mk-hub__inner" />
        {points.map((p, i) => (
          <motion.line
            key={i}
            x1="50"
            y1="50"
            x2={p.x}
            y2={p.y}
            className="mk-hub__spoke"
            variants={SPOKE}
            custom={i}
          />
        ))}
        {reduce
          ? null
          : points.map((p, i) => (
              <circle key={i} r="0.9" className="mk-hub__spark">
                <animateMotion
                  dur={`${2.6 + (i % 3) * 0.5}s`}
                  begin={`${1.2 + i * 0.3}s`}
                  repeatCount="6"
                  path={`M${p.x},${p.y} L50,50`}
                />
              </circle>
            ))}
      </svg>

      <motion.div className="mk-hub__core" variants={CORE}>
        <span className="mk-hub__halo" />
        <LogoMark className="size-9 sm:size-11" />
        <span className="mt-1.5 font-mk-display text-sm font-bold sm:text-base">{name}</span>
      </motion.div>

      {points.map((p, i) => {
        const Icon = ICONS[i] ?? Users;
        return (
          // Keyed by position, not label: the pieces stay mounted when the
          // language changes, so the drawn diagram does not vanish.
          <motion.div
            key={i}
            className="mk-hub__node"
            style={{ left: `${p.x}%`, top: `${p.y}%` }}
            variants={NODE}
            custom={i}
          >
            <span className="mk-hub__icon">
              <Icon className="size-4" />
            </span>
            <span className="mk-hub__label">{p.label}</span>
          </motion.div>
        );
      })}
    </motion.div>
  );
}
