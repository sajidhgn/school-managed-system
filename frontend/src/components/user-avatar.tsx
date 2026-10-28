"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/misc";
import { avatarSrc } from "@/lib/api/resources";
import { initials } from "@/lib/utils";

/**
 * A member's profile photo, or their initials when they have none.
 *
 * The initials also stand in while the photo loads, and stay if it fails to —
 * Radix only swaps the fallback out once the image has actually decoded, so a
 * deleted file never shows as a broken-image icon.
 */
export function UserAvatar({
  name,
  avatarUrl,
  className,
  fallbackClassName,
}: {
  name: string;
  avatarUrl: string | null | undefined;
  className?: string;
  fallbackClassName?: string;
}) {
  const src = avatarSrc(avatarUrl);
  return (
    <Avatar className={className}>
      {src ? <AvatarImage src={src} alt="" className="object-cover" /> : null}
      <AvatarFallback className={fallbackClassName}>{initials(name)}</AvatarFallback>
    </Avatar>
  );
}
