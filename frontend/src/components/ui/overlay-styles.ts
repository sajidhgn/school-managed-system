/**
 * HeroUI's overlay motion, for the panel's Radix overlays.
 *
 * HeroUI drives its popovers and modals from React Aria's `data-entering` /
 * `data-exiting`; Radix exposes `data-state` instead. These are the same
 * animations — the same tw-animate-css steps, durations and curves as HeroUI's
 * popover.css and modal.css — keyed on Radix's attributes, so a dropdown, a
 * select and a dialog open the way HeroUI's do.
 */

/** A floating panel: grows out of its trigger, leaves faster than it came. */
export const popoverClasses = [
  "rounded-xl border border-border bg-popover text-popover-foreground shadow-[var(--shadow-overlay)]",
  "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-90 data-[state=open]:duration-150",
  "data-[side=bottom]:slide-in-from-top-1 data-[side=top]:slide-in-from-bottom-1",
  "data-[side=left]:slide-in-from-right-1 data-[side=right]:slide-in-from-left-1",
  "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:duration-100",
  "data-[state=closed]:pointer-events-none",
].join(" ");

/** A row in a menu or listbox: a gray fill under the pointer, a press-in. */
export const menuItemClasses = [
  "relative flex min-h-9 cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none",
  "transition-[background-color,transform] duration-150 ease-out active:scale-[0.98]",
  "data-[highlighted]:bg-[var(--default)]",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
  "[&_svg]:size-4 [&_svg]:shrink-0",
].join(" ");

export const backdropClasses = [
  "fixed inset-0 z-50 bg-[var(--backdrop)] backdrop-blur-[2px]",
  "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-150",
  "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-100",
].join(" ");

/**
 * The dialog itself: settles from slightly large and slightly low, on HeroUI's
 * modal curve; leaves by shrinking away.
 */
export const modalClasses = [
  "rounded-2xl bg-card text-card-foreground shadow-[var(--shadow-overlay)]",
  "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-105 data-[state=open]:slide-in-from-bottom-1",
  "data-[state=open]:duration-250 data-[state=open]:ease-out-quad",
  "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
  "data-[state=closed]:duration-100 data-[state=closed]:ease-out-quad",
].join(" ");

/** HeroUI's close button: a small gray tile that presses in. */
export const closeButtonClasses = "close-button close-button--default";
