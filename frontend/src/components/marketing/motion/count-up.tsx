"use client";

import { animate, useInView, useReducedMotion } from "motion/react";
import { useEffect, useLayoutEffect, useRef } from "react";

import { EASE_OUT } from "./reveal";

/**
 * A number that counts up from zero the first time it scrolls into view.
 *
 * The server renders the final figure, so it is right without JavaScript and for
 * crawlers. Only once hydrated, and only while still off screen, is it reset to
 * zero to count up later; one already on screen is left alone.
 */
export function CountUp({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -12% 0px" });
  const reduce = useReducedMotion();
  const armed = useRef(false);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || reduce) return;
    const box = node.getBoundingClientRect();
    if (box.top > window.innerHeight) {
      node.textContent = format(0);
      armed.current = true;
    }
  }, [reduce]);

  useEffect(() => {
    const node = ref.current;
    if (!node || !inView || !armed.current) return;
    const controls = animate(0, value, {
      duration: 1.6,
      ease: EASE_OUT,
      onUpdate: (v) => {
        node.textContent = format(Math.round(v));
      },
    });
    return () => controls.stop();
  }, [inView, value]);

  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}

function format(value: number) {
  return new Intl.NumberFormat("en").format(value);
}
