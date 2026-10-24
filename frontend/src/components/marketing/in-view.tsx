"use client";

import { useEffect, useRef, useState, type HTMLAttributes } from "react";

/**
 * Sets `data-in` on itself the first time it scrolls into view, and never unsets it.
 *
 * This is the public site's only scroll JavaScript. Every reveal, stamp and
 * counter is plain CSS keyed off `[data-in]` (see (marketing)/marketing.css), so
 * the demos stay server components and nothing re-renders as the visitor scrolls.
 */
export function InView({
  threshold = 0.25,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { threshold?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || seen) return;
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      // The bottom inset waits until the element is properly on screen, so a
      // stamp does not land while it is still under the fold.
      { threshold, rootMargin: "0px 0px -8% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [seen, threshold]);

  return (
    <div ref={ref} data-in={seen ? "" : undefined} {...rest}>
      {children}
    </div>
  );
}
