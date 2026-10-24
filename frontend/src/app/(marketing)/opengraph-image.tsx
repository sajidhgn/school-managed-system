import { OG_SIZE, renderOgImage } from "@/components/marketing/og-card";
import { SITE_TAGLINE } from "@/lib/site";

// The preview for every public page without its own (home, pricing, features).
export const alt = `SchoolYar: ${SITE_TAGLINE}`;
export const size = OG_SIZE;
export const contentType = "image/png";

export default function Image() {
  return renderOgImage({
    eyebrow: SITE_TAGLINE,
    title: "Snap the diary. Parents get it on WhatsApp.",
  });
}
