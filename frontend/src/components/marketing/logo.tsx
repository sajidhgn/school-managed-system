import { cn } from "@/lib/utils";

/**
 * SchoolYar's mark: an exercise-book page in blue, ruled, with a stroke of ink.
 * A fixed illustration, so its colours stay the same on black, white and blue.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <rect x="3" y="2" width="26" height="28" rx="6" fill="#2447f5" />
      <rect x="7" y="6" width="18" height="20" rx="2" fill="#ffffff" />
      <path d="M9.5 12h13M9.5 16h13M9.5 20h13" stroke="#c9cfdc" strokeWidth="1.3" />
      <path d="M12 6v20" stroke="#2447f5" strokeWidth="1.4" />
      <path
        d="M14 15.4c1.5-2.5 3-2.7 4-1.2s2.5 1.5 4.1-.9"
        fill="none"
        stroke="#0a0c10"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}
