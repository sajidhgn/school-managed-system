"use client";

import { motion } from "motion/react";
import type { PointerEvent, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A card that lifts on hover and carries a soft blue light under the pointer.
 *
 * The light is a CSS gradient positioned from `--mx` / `--my` (marketing.css,
 * `.mk-spot`), so moving the pointer costs two custom-property writes and no
 * React render.
 */
export function Spotlight({
  className,
  children,
  lift = -4,
}: {
  className?: string;
  children: ReactNode;
  lift?: number;
}) {
  const track = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--mx", `${event.clientX - box.left}px`);
    event.currentTarget.style.setProperty("--my", `${event.clientY - box.top}px`);
  };

  return (
    <motion.div
      className={cn("mk-spot", className)}
      onPointerMove={track}
      whileHover={{ y: lift }}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
    >
      {children}
    </motion.div>
  );
}
