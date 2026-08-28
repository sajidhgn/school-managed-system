/**
 * The seam between a portalled select menu and the Radix dialog it opens over.
 *
 * =============================================================================
 * THE BUG THIS EXISTS TO PREVENT
 * =============================================================================
 *   `TeacherSelect` renders its menu into `document.body`, because the dialog clips
 *   anything drawn inside it. That puts the menu OUTSIDE `DialogContent` in the DOM
 *   -- and Radix's dismissable layer closes the dialog on any pointer-down whose
 *   target is outside that node.
 *
 *   So the menu opens, you click the teacher you wanted, and the entire form closes
 *   without saving. It looks like the dialog randomly shuts when you pick someone.
 *
 *   The fix is to tell the dialog that this particular "outside" is really inside: a
 *   marker class on the menu, and a predicate the dialog checks before dismissing.
 *
 * Kept in its own module deliberately. `section-form-dialog` needs the predicate, but
 * imports `TeacherSelect` lazily to keep react-select out of the page bundle --
 * importing the predicate from that file would drag the whole library back in.
 */

/** Marker class applied to the portalled menu. Referenced by `isInsidePortalledMenu`. */
export const SELECT_MENU_CLASS = "js-portalled-select-menu";

/**
 * Whether a dismiss event came from inside a portalled select menu.
 *
 * Radix hands these events a `target` on `detail.originalEvent`; the plain `target`
 * is read too so the same predicate works for both the pointer-down and focus
 * variants of the callback.
 */
export function isInsidePortalledMenu(event: { target?: EventTarget | null }): boolean {
  const target = event.target;
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest(`.${SELECT_MENU_CLASS}`));
}
