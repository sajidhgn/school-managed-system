import * as React from "react";
import { chipVariants } from "@heroui/styles";

import { cn } from "@/lib/utils";

/**
 * Status pill, drawn as a HeroUI chip.
 *
 * Colour here is meaningful, never decorative: `success` = healthy/active,
 * `warning` = needs a human decision, `destructive` = blocked. Variants also
 * differ in weight and text, so status is never conveyed by hue alone.
 *
 * Soft chips throughout — a tinted fill with darker text of the same hue — so a
 * table full of statuses stays readable instead of turning into a row of
 * solid blocks. `default` is the brand blue; `neutral` is gray.
 */

type Variant = "default" | "neutral" | "success" | "warning" | "destructive" | "outline";

const CHIP: Record<Variant, Parameters<typeof chipVariants>[0]> = {
  default: { color: "accent", variant: "soft" },
  neutral: { color: "default", variant: "soft" },
  success: { color: "success", variant: "soft" },
  warning: { color: "warning", variant: "soft" },
  destructive: { color: "danger", variant: "soft" },
  outline: { color: "default", variant: "tertiary" },
};

function badgeVariants({ variant = "default" }: { variant?: Variant | null } = {}) {
  const v = variant ?? "default";
  return cn(
    chipVariants(CHIP[v]).base(),
    "gap-1 [&_svg]:size-3",
    v === "outline" && "border border-border",
  );
}

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: Variant | null;
}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
