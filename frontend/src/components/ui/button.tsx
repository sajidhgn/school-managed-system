import * as React from "react";
import { buttonVariants as heroButtonVariants } from "@heroui/styles";
import { Slot } from "@radix-ui/react-slot";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The panel's button, drawn by HeroUI.
 *
 * The API is the panel's own (`variant`, `size`, `asChild`, `loading`), so the
 * eighty-odd call sites did not change; what renders is HeroUI's button class —
 * its colours from the tokens in globals.css, the control radius (heroui.css
 * overrides HeroUI's pill), and its motion: a quick press-in to 97% and an
 * eased hover. `@heroui/styles` returns class names
 * only, so this stays usable from server components and as a Radix `asChild`
 * trigger, neither of which HeroUI's React `Button` allows.
 *
 * `w-auto` undoes HeroUI's `w-fit`. The panel's forms put a submit button in a
 * grid cell and expect it to fill the column, as a native button does.
 */

type Variant = "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
type Size = "default" | "sm" | "lg" | "icon";

const HERO_VARIANT = {
  default: "primary",
  destructive: "danger",
  outline: "outline",
  secondary: "tertiary",
  ghost: "ghost",
} as const;

const LINK_CLASSES =
  "inline-flex items-center gap-1.5 rounded-sm text-sm font-medium text-primary underline-offset-4 transition-colors hover:underline disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0";

function buttonVariants({
  variant = "default",
  size = "default",
  className,
}: { variant?: Variant | null; size?: Size | null; className?: string } = {}) {
  const v = variant ?? "default";
  if (v === "link") return cn(LINK_CLASSES, className);
  const s = size ?? "default";
  return cn(
    heroButtonVariants({
      variant: HERO_VARIANT[v],
      size: s === "sm" ? "sm" : s === "lg" ? "lg" : "md",
      isIconOnly: s === "icon",
    }),
    "w-auto",
    className,
  );
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant | null;
  size?: Size | null;
  asChild?: boolean;
  /** Shows a spinner and blocks input — use for in-flight mutations. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={buttonVariants({ variant, size, className })}
        ref={ref}
        disabled={disabled || loading}
        data-pending={loading || undefined}
        {...props}
      >
        {loading ? (
          <>
            <Loader2 className="animate-spin" aria-hidden />
            {children}
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
