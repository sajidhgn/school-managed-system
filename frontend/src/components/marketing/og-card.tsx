import { ImageResponse } from "next/og";

/**
 * The link-preview image for public pages (1200×630), in the site's own look: a
 * black band with a blueprint grid, a blue glow and the page's headline, so a
 * link shared in a WhatsApp group reads as SchoolYar before anyone taps it.
 */

export const OG_SIZE = { width: 1200, height: 630 };

const FOOTER = "Fees and challans · WhatsApp diary · Test papers · Attendance";

/**
 * The display face, fetched from Google Fonts and subset to the characters on
 * the card. A failed fetch (offline build) falls back to the default face rather
 * than failing the image.
 */
async function loadDisplayFont(text: string): Promise<ArrayBuffer | null> {
  try {
    const cssUrl = `https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@700&text=${encodeURIComponent(text)}`;
    const css = await (await fetch(cssUrl)).text();
    const fontUrl = css.match(/src: url\((.+?)\) format\('(?:opentype|truetype)'\)/)?.[1];
    if (!fontUrl) return null;
    const response = await fetch(fontUrl);
    return response.ok ? await response.arrayBuffer() : null;
  } catch {
    return null;
  }
}

export async function renderOgImage({ eyebrow, title }: { eyebrow: string; title: string }) {
  // Subset to every character on the card. A glyph missing from the subset would
  // fall back to the default face mid-word.
  const font = await loadDisplayFont(`SchoolYar${eyebrow}${title}${FOOTER}`);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          position: "relative",
          backgroundColor: "#0a0c10",
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)",
          backgroundSize: "56px 56px",
          fontFamily: "Zilla Slab",
          fontWeight: 700,
        }}
      >
        <div
          style={{
            position: "absolute",
            top: -260,
            right: -220,
            width: 760,
            height: 760,
            borderRadius: 760,
            backgroundImage: "radial-gradient(circle, rgba(36,71,245,0.55), rgba(36,71,245,0) 62%)",
          }}
        />
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            width: "100%",
            padding: "64px 80px 60px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <svg width="52" height="52" viewBox="0 0 32 32">
              <rect x="3" y="2" width="26" height="28" rx="6" fill="#2447f5" />
              <rect x="7" y="6" width="18" height="20" rx="2" fill="#ffffff" />
              <path d="M9.5 12h13M9.5 16h13M9.5 20h13" stroke="#c9cfdc" strokeWidth="1.3" />
              <path d="M12 6v20" stroke="#2447f5" strokeWidth="1.4" />
            </svg>
            <div style={{ fontSize: 42, color: "#ffffff" }}>SchoolYar</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 26, color: "#8ea2ff" }}>
              <div style={{ width: 12, height: 12, borderRadius: 12, backgroundColor: "#2447f5" }} />
              {eyebrow}
            </div>
            <div
              style={{
                fontSize: title.length > 48 ? 64 : 76,
                lineHeight: 1.04,
                letterSpacing: -2,
                color: "#ffffff",
                maxWidth: 980,
              }}
            >
              {title}
            </div>
          </div>
          <div style={{ fontSize: 24, color: "#a1a7b3" }}>{FOOTER}</div>
        </div>
      </div>
    ),
    {
      ...OG_SIZE,
      fonts: font ? [{ name: "Zilla Slab", data: font, weight: 700, style: "normal" }] : undefined,
    },
  );
}
