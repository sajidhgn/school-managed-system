import { cn } from "@/lib/utils";

/**
 * A campus's logo, or its initial on a tinted tile when it has none.
 *
 * `src` is whatever the API stored — an `https://` link or an inline `data:image/`
 * URI (see `LogoInput`) — so a plain <img> rather than `next/image`, which would
 * need every school's logo host allow-listed in the config.
 *
 * The caller resolves the fallback chain (campus → organization) before passing
 * `src`; this component only decides between the image and the initial.
 */
export function SchoolLogo({
  src,
  name,
  className,
}: {
  src: string | null | undefined;
  name: string | null | undefined;
  className?: string;
}) {
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt="" className={cn("size-8 shrink-0 rounded-md object-contain", className)} />
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-md bg-primary/10 text-sm font-semibold text-primary",
        className,
      )}
    >
      {name?.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
