import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A native `<select>`, styled to match the rest of the inputs.
 *
 * WHY THIS EXISTS ALONGSIDE THE RADIX `Select`
 *   The Radix version is a custom listbox: better for rich options, and it composes
 *   with `<Controller>`. But it does not accept a ref+onChange pair the way an input
 *   does, so `{...register("role_id")}` does not work with it — every usage needs a
 *   wrapper.
 *
 *   For plain string choices in a form (a role, a month, a status) the native
 *   element is simpler, forwards its ref, works with `register` directly, and gets
 *   the platform's own keyboard handling and mobile picker for free. Reach for the
 *   Radix one when an option needs more than a label.
 *
 * `pe-8` (padding-inline-end) leaves room for the chevron on whichever side the
 * writing direction puts it.
 */
export const NativeSelect = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        "h-9 w-full appearance-none rounded-md border border-input bg-card px-3 pe-8 text-sm shadow-sm",
        "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-[invalid=true]:border-destructive",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown
      className="pointer-events-none absolute end-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      aria-hidden
    />
  </div>
));
NativeSelect.displayName = "NativeSelect";
