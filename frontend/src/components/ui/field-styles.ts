/**
 * The look every text field, select and textarea shares, after HeroUI's fields:
 * the control radius, a hairline border that darkens under the pointer, and on focus a
 * blue border with a faint halo that eases in rather than snapping on.
 *
 * One string so the four kinds of field cannot drift apart. Selects use `focus:`
 * where text fields use `focus-visible:`: Chrome does not count a mouse click on a
 * `<select>` as focus-visible, and a picker that gives no sign it is open reads as
 * broken.
 */
const BASE = [
  "w-full rounded-control border border-input bg-card text-sm text-foreground",
  "shadow-[0_1px_2px_0_rgb(10_12_16/0.04)]",
  "transition-[border-color,box-shadow,background-color] duration-150 ease-out",
  "hover:border-[color:var(--field-border-hover)]",
  "placeholder:text-muted-foreground",
  "disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-input",
  "aria-[invalid=true]:border-destructive",
].join(" ");

export const fieldClasses = [
  BASE,
  "focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/20",
  "aria-[invalid=true]:focus-visible:ring-destructive/20",
].join(" ");

export const selectFieldClasses = [
  BASE,
  "focus:border-ring focus:outline-none focus:ring-[3px] focus:ring-ring/20",
  "aria-[invalid=true]:focus:ring-destructive/20",
].join(" ");
