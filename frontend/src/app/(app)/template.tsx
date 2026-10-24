/**
 * Wraps every page of the panel, between the shell and the page.
 *
 * A template, not a layout, because Next re-mounts it on every navigation: the
 * wrapper's entrance animation (`panel-enter`, globals.css) therefore plays each
 * time a module opens, while the shell around it — sidebar, header, search —
 * stays mounted and still.
 */
export default function AppTemplate({ children }: { children: React.ReactNode }) {
  return <div className="panel-enter">{children}</div>;
}
