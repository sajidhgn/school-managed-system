"use client";

import { motion, useMotionValueEvent, useScroll, useSpring } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";

/**
 * The sticky header's frame: see-through over the black hero, then a blurred,
 * bordered bar once the page scrolls, with a thin blue line along its foot that
 * fills as the visitor reads down the page.
 */
export function HeaderShell({ children }: { children: ReactNode }) {
  const { scrollY, scrollYProgress } = useScroll();
  const [scrolled, setScrolled] = useState(false);
  const progress = useSpring(scrollYProgress, { stiffness: 220, damping: 32, restDelta: 0.001 });

  useMotionValueEvent(scrollY, "change", (y) => setScrolled(y > 8));
  useEffect(() => setScrolled(window.scrollY > 8), []);

  return (
    <header className="mk-night mk-header mk-heroui" data-scrolled={scrolled ? "" : undefined}>
      {children}
      <motion.div className="mk-progress" style={{ scaleX: progress }} aria-hidden />
    </header>
  );
}
