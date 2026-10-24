"use client";

import { motion, useInView, type Variants } from "motion/react";
import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * Scroll reveals for the public site, in Motion.
 *
 * Each element fades and rises the first time it comes on screen. The children
 * are usually server components; only this wrapper ships to the browser.
 *
 * Shown is a state the element holds (`animate`), not a one-off gesture
 * (`whileInView`), so the reveal survives a re-render. Switching the language
 * refreshes the page, and list items keyed by their text mount afresh; Motion
 * does not replay a list's finished stagger for an item that joins late, so a
 * `StaggerItem` that mounts into a list already shown starts shown. Anything
 * already scrolled past when it mounts is shown at once rather than waiting to
 * be scrolled back to.
 *
 * `data-reveal` is what marketing.css shows at full opacity when scripting is off,
 * so a visitor without JavaScript never meets a blank section. Reduced motion is
 * handled once, by the MotionConfig in heroui-scope.tsx: elements still fade in,
 * but nothing moves.
 */

export const EASE_OUT = [0.2, 0.7, 0.2, 1] as const;

/** Waits until the element is a little way onto the screen, not at its very edge. */
const VIEWPORT = { once: true, margin: "0px 0px -12% 0px" } as const;

/** Whether `ref` has been on screen, or was already above it when it mounted. */
export function useRevealed(ref: RefObject<Element | null>): boolean {
  const inView = useInView(ref, VIEWPORT);
  const [passed, setPassed] = useState(false);

  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    if (box && box.bottom < 0) setPassed(true);
  }, [ref]);

  return inView || passed;
}

const TAGS = {
  div: motion.div,
  li: motion.li,
  ul: motion.ul,
  ol: motion.ol,
  dl: motion.dl,
  p: motion.p,
  span: motion.span,
} as const;

type Tag = keyof typeof TAGS;

type Props = {
  as?: Tag;
  className?: string;
  style?: CSSProperties;
  id?: string;
  children: ReactNode;
};

/** One element that fades and rises into place. */
export function Reveal({ as = "div", delay = 0, y = 24, ...rest }: Props & { delay?: number; y?: number }) {
  const Tag = TAGS[as] as typeof motion.div;
  const ref = useRef<HTMLDivElement>(null);
  const shown = useRevealed(ref);
  return (
    <Tag
      ref={ref}
      data-reveal=""
      initial={{ opacity: 0, y }}
      animate={shown ? { opacity: 1, y: 0 } : { opacity: 0, y }}
      transition={{ duration: 0.75, ease: EASE_OUT, delay }}
      {...rest}
    />
  );
}

/** Whether the enclosing `Stagger` has already revealed its items. */
const StaggerShown = createContext(false);

const ITEM: Variants = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.65, ease: EASE_OUT } },
};

/** A list whose `StaggerItem`s arrive one after another. */
export function Stagger({ as = "div", gap = 0.08, delay = 0, ...rest }: Props & { gap?: number; delay?: number }) {
  const Tag = TAGS[as] as typeof motion.div;
  const ref = useRef<HTMLDivElement>(null);
  const shown = useRevealed(ref);
  return (
    <StaggerShown.Provider value={shown}>
      <Tag
        ref={ref}
        initial="hidden"
        animate={shown ? "show" : "hidden"}
        variants={{ hidden: {}, show: { transition: { staggerChildren: gap, delayChildren: delay } } }}
        {...rest}
      />
    </StaggerShown.Provider>
  );
}

export function StaggerItem({ as = "div", ...rest }: Props) {
  const Tag = TAGS[as] as typeof motion.div;
  // Read once, at mount. An item present for the reveal takes part in the
  // stagger; one that joins a list already shown runs its own fade-in.
  const [late] = useState(useContext(StaggerShown));
  return <Tag data-reveal="" variants={ITEM} {...(late ? { initial: "hidden", animate: "show" } : {})} {...rest} />;
}
