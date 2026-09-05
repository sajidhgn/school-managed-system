"use client";

import * as React from "react";
import { Cake, GraduationCap, Hash, UserRound } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import type { CardDesignConfig, StudentListRow } from "@/lib/api/types";
import { cn, formatDate } from "@/lib/utils";

/** The API's `CardDesignConfig` with every knob present. */
export type ResolvedCardDesign = Required<CardDesignConfig>;

/**
 * What the card needs to know about the campus: identity, effective branding
 * (branch override or organization default, resolved by the page) and the
 * saved card template.
 */
export type CardSchool = {
  id: string;
  name: string;
  code: string;
  phone: string | null;
  email: string | null;
  address: string | null;
  city: string | null;
  logoUrl: string | null;
  themeColors: string[] | null;
  cardDesign: CardDesignConfig | null;
};

/**
 * Must mirror the backend defaults in `CardDesignConfig` (tenancy schemas):
 * a campus with no saved design renders exactly what an old saved `{}` does.
 */
export const DEFAULT_CARD_DESIGN: ResolvedCardDesign = {
  design: "classic",
  orientation: "landscape",
  logo_position: "center",
  photo_shape: "rounded",
  photo_size: "md",
  photo_position: "start",
  show_admission_number: true,
  show_class: true,
  show_date_of_birth: true,
  show_guardian_name: true,
  contact_number: "guardian",
  show_qr: true,
  rules: [],
  show_validity: true,
  found_notice: "",
  contact_line: "",
};

export const DESIGN_LABELS: Record<ResolvedCardDesign["design"], string> = {
  classic: "Classic",
  bold: "Bold",
  gradient: "Gradient",
  stripe: "Stripe",
  minimal: "Minimal",
  chevron: "Chevron",
  panel: "Side panel",
  wave: "Wave",
  mosaic: "Mosaic",
  duotone: "Duotone",
  outline: "Outline",
  ribbon: "Ribbon",
  dots: "Dots",
  blob: "Blob",
  rings: "Rings",
  tide: "Tide",
  slate: "Slate",
  banner: "Banner",
  corner: "Corner",
  grid: "Grid",
  prism: "Prism",
  crest: "Crest",
  frame: "Frame",
  sash: "Sash",
  orbit: "Orbit",
  aurora: "Aurora",
  pillar: "Pillar",
  halo: "Halo",
  graphite: "Graphite",
  breeze: "Breeze",
  band: "Band",
};

/**
 * When the school never picked theme colours, designs still need some to differ
 * from each other — neutral slates, not the product's brand colours, so an
 * unbranded school's cards don't quietly advertise us.
 */
export const FALLBACK_PALETTE = ["#334155", "#64748b"];

export function resolveCardDesign(school: CardSchool | null): ResolvedCardDesign {
  return { ...DEFAULT_CARD_DESIGN, ...(school?.cardDesign ?? {}) };
}

export function resolvePalette(school: CardSchool | null): string[] {
  return school?.themeColors?.length ? school.themeColors : FALLBACK_PALETTE;
}

/** One year on from an ISO date — the card's expiry, session-style. */
function addOneYear(isoDate: string): string {
  const date = new Date(isoDate);
  date.setFullYear(date.getFullYear() + 1);
  return date.toISOString().slice(0, 10);
}

/** Black or white, whichever reads on the given `#RRGGBB` background. */
function readableOn(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#111111" : "#ffffff";
}

/**
 * Everything a design is allowed to change: colour, plus three structural
 * switches (`chips`, `panel`, `sweep`) the print-shop styles need. Designs
 * still restyle the ONE card layout rather than each bringing their own
 * markup: eight designs × two orientations as sixteen hand-written layouts is
 * how the guardian line goes missing from exactly one of them.
 *
 * The palette is ordered: `palette[0]` is the primary, `palette[1]` the
 * secondary (falling back to the primary for a one-colour school, so every
 * design renders regardless of how many colours were configured).
 */
export type CardDesignTokens = {
  cardStyle?: React.CSSProperties;
  headerStyle?: React.CSSProperties;
  footerStyle?: React.CSSProperties;
  /** 3mm rule down the leading edge (the "stripe" design). */
  stripeColor: string | null;
  /** Detail lines marked by little icon tags instead of text labels —
   * `arrow` is the pointed label of the chevron sample cards, `round` the
   * dot icons of the wave/panel ones. */
  chips: { shape: "arrow" | "round"; background: string; color: string } | null;
  /** A filled colour panel on the trailing edge that carries the photo —
   * `chevron` points into the card, `straight` is a plain block. */
  panel: { clip: "chevron" | "straight"; background: string; color: string } | null;
  /** Curved decorative colour sweep — behind the leading edge (`start`, the
   * default) or the trailing/bottom edge (`end`). */
  sweep: { background: string; edge?: "start" | "end" } | null;
  /** Whole-card background decoration, always behind the content: the faint
   * grey chevron watermark of the sample cards, or one of the coloured
   * patterns in the school's palette. Decoration only — never information. */
  backdrop:
    | { kind: "chevrons" }
    | {
        kind: "mosaic" | "dots" | "grid" | "diagonal" | "blob" | "rings" | "tri";
        primary: string;
        secondary: string;
      }
    | null;
};

export function designTokens(
  design: ResolvedCardDesign["design"],
  palette: string[],
): CardDesignTokens {
  const primary = palette[0] ?? FALLBACK_PALETTE[0];
  const secondary = palette[1] ?? primary;
  const onPrimary = readableOn(primary);
  const onSecondary = readableOn(secondary);
  const none = { stripeColor: null, chips: null, panel: null, sweep: null, backdrop: null };
  switch (design) {
    case "classic":
      // The primary as a header band; the rest of the card stays quiet.
      return {
        ...none,
        headerStyle: { backgroundColor: primary, color: onPrimary },
      };
    case "bold":
      // Primary up top, secondary along the bottom, primary border: the design
      // for schools that picked colours because they want to see them.
      return {
        ...none,
        cardStyle: { borderColor: primary },
        headerStyle: { backgroundColor: primary, color: onPrimary },
        footerStyle: { backgroundColor: secondary, color: onSecondary },
      };
    case "gradient":
      // Primary flowing into secondary — the design that exists BECAUSE the
      // palette does; with one colour it degrades to a flat band (= classic).
      return {
        ...none,
        headerStyle: {
          backgroundImage: `linear-gradient(135deg, ${primary}, ${secondary})`,
          color: onPrimary,
        },
      };
    case "stripe":
      // No filled areas at all — a 3mm rule down the leading edge and the
      // school name in the primary. The safest design on printers that ignore
      // `print-color-adjust` and refuse backgrounds: a border always prints.
      return { ...none, headerStyle: { color: primary }, stripeColor: primary };
    case "minimal":
      // Monochrome regardless of branding, for schools that photocopy.
      return { ...none };
    case "chevron":
      // The print-shop favourite: a colour wedge pointing into the card
      // carries the photo, each detail wears a pointed label tag, and the
      // faint grey chevron watermark of the sample cards runs behind it all.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "arrow", background: primary, color: onPrimary },
        panel: { clip: "chevron", background: primary, color: onPrimary },
        backdrop: { kind: "chevrons" },
      };
    case "panel":
      // A straight colour block down the trailing edge with the photo in it;
      // details get quiet round icon dots in the secondary, and the same
      // watermark keeps the white half from feeling empty.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: secondary, color: onSecondary },
        panel: { clip: "straight", background: primary, color: onPrimary },
        backdrop: { kind: "chevrons" },
      };
    case "wave":
      // A curved gradient sweep behind the leading edge — the photo floats on
      // it — with round icon dots on the detail lines.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        sweep: { background: `linear-gradient(160deg, ${primary}, ${secondary})` },
      };
    case "mosaic":
      // The geometric sample card: a soft low-poly band in the school's
      // colours along the top, quiet round icon dots on the details.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        backdrop: { kind: "mosaic", primary, secondary },
      };
    case "duotone":
      // Both brand colours meeting at a hard 50/50 seam across the header.
      return {
        ...none,
        headerStyle: {
          backgroundImage: `linear-gradient(90deg, ${primary} 0%, ${primary} 50%, ${secondary} 50%, ${secondary} 100%)`,
          color: onPrimary,
        },
        chips: { shape: "round", background: primary, color: onPrimary },
      };
    case "outline":
      // The card's border IS the brand: a primary frame around a quiet card.
      return {
        ...none,
        cardStyle: { borderColor: primary },
        headerStyle: { color: primary },
        chips: { shape: "round", background: secondary, color: onSecondary },
      };
    case "ribbon":
      // Two translucent diagonal bands crossing the card like a sash.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "arrow", background: primary, color: onPrimary },
        backdrop: { kind: "diagonal", primary, secondary },
      };
    case "dots":
      // A filled header over a faint polka-dot field in the secondary.
      return {
        ...none,
        headerStyle: { backgroundColor: primary, color: onPrimary },
        chips: { shape: "round", background: secondary, color: onSecondary },
        backdrop: { kind: "dots", primary, secondary },
      };
    case "blob":
      // Soft organic colour blobs pooling in the trailing corner.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        backdrop: { kind: "blob", primary, secondary },
      };
    case "rings":
      // Concentric circles radiating from the bottom corner.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: secondary, color: onSecondary },
        backdrop: { kind: "rings", primary, secondary },
      };
    case "tide":
      // The wave's mirror: the gradient sweep rises from the trailing edge
      // (bottom, in portrait) instead of the leading one.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        sweep: {
          background: `linear-gradient(200deg, ${primary}, ${secondary})`,
          edge: "end",
        },
      };
    case "slate":
      // Secondary header, primary edge rule and pointed tags — the two
      // colours doing different jobs instead of shading one another.
      return {
        ...none,
        headerStyle: { backgroundColor: secondary, color: onSecondary },
        stripeColor: primary,
        chips: { shape: "arrow", background: primary, color: onPrimary },
      };
    case "banner":
      // Gradient header and a filled secondary footer: the dressed-up
      // sibling of "gradient" for schools that want colour on both edges.
      return {
        ...none,
        headerStyle: {
          backgroundImage: `linear-gradient(135deg, ${primary}, ${secondary})`,
          color: onPrimary,
        },
        footerStyle: { backgroundColor: secondary, color: onSecondary },
        chips: { shape: "round", background: primary, color: onPrimary },
      };
    case "corner":
      // Flat geometric triangles stacked in the top trailing corner.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "arrow", background: primary, color: onPrimary },
        backdrop: { kind: "tri", primary, secondary },
      };
    case "grid":
      // A faint blueprint grid across the card, everything else quiet.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        backdrop: { kind: "grid", primary, secondary },
      };
    // ----- Combinations: the same building blocks recomposed. --------------
    case "prism":
      // Mosaic band up top AND a secondary photo panel — the geometric
      // sample card at full volume.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        panel: { clip: "straight", background: secondary, color: onSecondary },
        backdrop: { kind: "mosaic", primary, secondary },
      };
    case "crest":
      // A classic filled header with the watermark and pointed tags — the
      // traditional face wearing the print-shop trim.
      return {
        ...none,
        headerStyle: { backgroundColor: primary, color: onPrimary },
        chips: { shape: "arrow", background: secondary, color: onSecondary },
        backdrop: { kind: "chevrons" },
      };
    case "frame":
      // Primary border and a filled primary footer: colour around the edges,
      // calm in the middle.
      return {
        ...none,
        cardStyle: { borderColor: primary },
        headerStyle: { color: primary },
        footerStyle: { backgroundColor: primary, color: onPrimary },
        chips: { shape: "round", background: primary, color: onPrimary },
      };
    case "sash":
      // The diagonal bands plus a secondary chevron panel — ribbon and wedge
      // together.
      return {
        ...none,
        headerStyle: { color: secondary },
        chips: { shape: "arrow", background: secondary, color: onSecondary },
        panel: { clip: "chevron", background: secondary, color: onSecondary },
        backdrop: { kind: "diagonal", primary, secondary },
      };
    case "orbit":
      // Gradient header over the concentric rings.
      return {
        ...none,
        headerStyle: {
          backgroundImage: `linear-gradient(135deg, ${primary}, ${secondary})`,
          color: onPrimary,
        },
        chips: { shape: "round", background: primary, color: onPrimary },
        backdrop: { kind: "rings", primary, secondary },
      };
    case "aurora":
      // The gradient reversed and the blobs pooling beneath it.
      return {
        ...none,
        headerStyle: {
          backgroundImage: `linear-gradient(315deg, ${primary}, ${secondary})`,
          color: onPrimary,
        },
        chips: { shape: "round", background: secondary, color: onSecondary },
        backdrop: { kind: "blob", primary, secondary },
      };
    case "pillar":
      // Edge rule in the primary, photo panel in the secondary: the two
      // colours holding opposite edges of the card.
      return {
        ...none,
        headerStyle: { color: primary },
        stripeColor: primary,
        chips: { shape: "arrow", background: primary, color: onPrimary },
        panel: { clip: "straight", background: secondary, color: onSecondary },
      };
    case "halo":
      // A primary photo panel with the rings radiating behind the details.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: primary, color: onPrimary },
        panel: { clip: "straight", background: primary, color: onPrimary },
        backdrop: { kind: "rings", primary, secondary },
      };
    case "graphite":
      // A fixed near-black header regardless of palette — the school's
      // colours appear only in the rule and the chips. For schools whose
      // brand colours are too light to carry a header.
      return {
        ...none,
        headerStyle: { backgroundColor: "#1f2937", color: "#ffffff" },
        stripeColor: primary,
        chips: { shape: "round", background: primary, color: onPrimary },
      };
    case "breeze":
      // The wave's sweep over the polka-dot field.
      return {
        ...none,
        headerStyle: { color: primary },
        chips: { shape: "round", background: secondary, color: onSecondary },
        sweep: { background: `linear-gradient(160deg, ${primary}, ${secondary})` },
        backdrop: { kind: "dots", primary, secondary },
      };
    case "band":
      // The laminated lanyard card from the sample photos: matching solid
      // bands top and bottom, framed in the secondary, plain text rows.
      return {
        ...none,
        cardStyle: { borderColor: secondary },
        headerStyle: { backgroundColor: primary, color: onPrimary },
        footerStyle: { backgroundColor: primary, color: onPrimary },
      };
  }
}

const PHOTO_SIZE_CLASSES: Record<
  ResolvedCardDesign["photo_size"],
  { frame: string; circle: string }
> = {
  sm: { frame: "h-14 w-12", circle: "h-14 w-14" },
  md: { frame: "h-20 w-16", circle: "h-20 w-20" },
  lg: { frame: "h-24 w-20", circle: "h-24 w-24" },
};

const PHOTO_SHAPE_CLASSES: Record<ResolvedCardDesign["photo_shape"], string> = {
  rounded: "rounded",
  circle: "rounded-full",
  square: "rounded-none",
};

/**
 * Soft low-poly band for the "mosaic" design: `[points, which colour, opacity]`
 * in a 100×24 viewBox stretched across the card's top. Opacities stay under
 * 0.45 so the school name printed over the band remains readable — the sample
 * card's pastel-polygon look, not a solid mural.
 */
const MOSAIC_TRIANGLES: Array<[string, "p" | "s", number]> = [
  ["0,0 14,0 6,12", "p", 0.4],
  ["14,0 30,0 20,10", "s", 0.3],
  ["6,12 20,10 12,22", "s", 0.15],
  ["20,10 30,0 34,14", "p", 0.22],
  ["30,0 48,0 40,12", "p", 0.12],
  ["34,14 40,12 44,24", "s", 0.26],
  ["40,12 48,0 56,10", "s", 0.42],
  ["48,0 66,0 56,10", "p", 0.18],
  ["56,10 66,0 70,12", "p", 0.32],
  ["66,0 84,0 76,10", "s", 0.14],
  ["70,12 76,10 80,20", "p", 0.1],
  ["76,10 84,0 92,12", "s", 0.24],
  ["84,0 100,0 92,12", "p", 0.36],
  ["92,12 100,0 100,16", "s", 0.16],
];

/**
 * Whole-card background decoration, rendered first inside the card so every
 * positioned content block paints over it. All sizes are percentages of the
 * card, so the same element decorates both orientations, the back face and
 * the gallery miniatures without a scale factor. Every pattern stays faint
 * enough (opacity-capped) for text laid over it to read. Decoration only —
 * no information lives here, so a printer that drops backgrounds loses
 * nothing but mood.
 */
export function CardBackdrop({ backdrop }: { backdrop: CardDesignTokens["backdrop"] }) {
  if (!backdrop) return null;

  if (backdrop.kind === "chevrons") {
    return (
      <svg
        aria-hidden
        className="absolute inset-0 h-full w-full text-foreground/[0.05]"
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
      >
        <path d="M62 0 L42 30 L62 60 L74 60 L54 30 L74 0 Z" fill="currentColor" />
        <path d="M82 0 L62 30 L82 60 L94 60 L74 30 L94 0 Z" fill="currentColor" />
      </svg>
    );
  }

  const { primary, secondary } = backdrop;

  switch (backdrop.kind) {
    case "mosaic":
      return (
        <svg
          aria-hidden
          className="absolute inset-x-0 top-0 h-[24%] w-full"
          viewBox="0 0 100 24"
          preserveAspectRatio="none"
        >
          {MOSAIC_TRIANGLES.map(([points, which, opacity], index) => (
            <polygon
              key={index}
              points={points}
              fill={which === "p" ? primary : secondary}
              fillOpacity={opacity}
            />
          ))}
        </svg>
      );
    case "dots":
      // `slice` keeps the dots circular in either orientation.
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="xMidYMid slice"
        >
          {Array.from({ length: 60 }, (_, index) => {
            const cx = 5 + (index % 10) * 10;
            const cy = 5 + Math.floor(index / 10) * 10;
            return (
              <circle key={index} cx={cx} cy={cy} r={1.2} fill={secondary} fillOpacity={0.18} />
            );
          })}
        </svg>
      );
    case "grid":
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="none"
        >
          {Array.from({ length: 9 }, (_, index) => (
            <line
              key={`v${index}`}
              x1={(index + 1) * 10}
              y1={0}
              x2={(index + 1) * 10}
              y2={60}
              stroke={primary}
              strokeOpacity={0.09}
              strokeWidth={0.4}
            />
          ))}
          {Array.from({ length: 5 }, (_, index) => (
            <line
              key={`h${index}`}
              x1={0}
              y1={(index + 1) * 10}
              x2={100}
              y2={(index + 1) * 10}
              stroke={primary}
              strokeOpacity={0.09}
              strokeWidth={0.4}
            />
          ))}
        </svg>
      );
    case "diagonal":
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="none"
        >
          <polygon points="60,0 74,0 44,60 30,60" fill={primary} fillOpacity={0.16} />
          <polygon points="80,0 90,0 60,60 50,60" fill={secondary} fillOpacity={0.22} />
        </svg>
      );
    case "blob":
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="none"
        >
          <ellipse cx="94" cy="8" rx="26" ry="20" fill={primary} fillOpacity={0.28} />
          <ellipse cx="104" cy="30" rx="24" ry="19" fill={secondary} fillOpacity={0.2} />
        </svg>
      );
    case "rings":
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="xMidYMid slice"
        >
          {[8, 14, 20].map((r, index) => (
            <circle
              key={r}
              cx="88"
              cy="54"
              r={r}
              fill="none"
              stroke={index % 2 ? secondary : primary}
              strokeOpacity={0.3 - index * 0.09}
              strokeWidth={2}
            />
          ))}
        </svg>
      );
    case "tri":
      return (
        <svg
          aria-hidden
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 60"
          preserveAspectRatio="none"
        >
          <polygon points="100,0 100,26 68,0" fill={primary} fillOpacity={0.5} />
          <polygon points="100,0 100,14 82,0" fill={secondary} fillOpacity={0.6} />
          <polygon points="68,0 82,0 75,9" fill={secondary} fillOpacity={0.25} />
        </svg>
      );
  }
}

/**
 * Prints ONLY the card sheet — both faces of the card, stacked, ready to trim
 * and laminate back-to-back. Hides everything else by visibility and
 * un-positions the dialog shell: the shell is `fixed` + translated, and an
 * absolutely positioned sheet inside a transformed ancestor would anchor to
 * the ancestor, not the page — so the transform must go too. The sheet (not
 * each card) is what anchors to the page's top corner, so the two faces stack
 * with a trim gap instead of printing on top of each other. Rendered by any
 * dialog that carries the `student-id-card-dialog` class and wants its sheet
 * printable.
 */
export function CardPrintStyle() {
  return (
    <style>{`
      @media print {
        body * { visibility: hidden; }
        /* The app's in-flow root would otherwise stretch the printed document
           into trailing blank pages; the dialog lives in a portal div that
           holds the sheet, which is the only body child that may keep height. */
        body > div:not(:has(.student-id-card-sheet)) { display: none !important; }
        .student-id-card-dialog {
          position: static !important;
          /* Tailwind v4 centers via the individual translate property, not
             transform — both must go, or the un-positioned dialog stays the
             sheet's containing block, shifted half a dialog off the page. */
          transform: none !important;
          translate: none !important;
          scale: none !important;
          rotate: none !important;
          max-height: none !important;
          overflow: visible !important;
          border: 0 !important;
          box-shadow: none !important;
          padding: 0 !important;
        }
        .student-id-card-sheet, .student-id-card-sheet * { visibility: visible !important; }
        .student-id-card-sheet {
          position: absolute;
          inset-inline-start: 0;
          top: 0;
          width: 100%;
          margin: 0;
        }
        .student-id-card-sheet .card-side-label { display: none !important; }
        .student-id-card {
          margin: 0 auto 6mm !important;
          break-inside: avoid;
          print-color-adjust: exact;
          -webkit-print-color-adjust: exact;
        }
      }
    `}</style>
  );
}

/**
 * The student ID card itself, rendered from a campus card template.
 *
 * Both orientations are the ISO/IEC 7810 ID-1 ("CR80") card exactly -- 85.60 ×
 * 53.98 mm, corner radius ~3.18 mm (the standard allows 2.88-3.48) -- just
 * rotated, so either trims to fit any standard badge holder or laminating
 * pouch. Sized in CSS millimetres, not pixels: mm survive the printer's DPI,
 * so a card printed at 100% scale really is bank-card sized.
 */
export function StudentCardView({
  student,
  school,
  config,
}: {
  student: StudentListRow;
  school: CardSchool | null;
  config: ResolvedCardDesign;
}) {
  const palette = resolvePalette(school);
  const tokens = designTokens(config.design, palette);
  const landscape = config.orientation === "landscape";

  // Portrait has no room for a sweep beside the content, so a leading-edge
  // sweep (wave) flows down from the top instead, behind the header — whose
  // text must then read on the gradient. A trailing-edge sweep (tide) sits at
  // the bottom and leaves the header alone, and the panel designs keep their
  // colour panel in portrait (it turns under the header and carries the
  // photo), so in both those cases the header stays as the tokens say.
  const sweepBehindHeader =
    !landscape && tokens.sweep ? (tokens.sweep.edge ?? "start") === "start" : false;
  const headerStyle: React.CSSProperties | undefined = sweepBehindHeader
    ? { ...tokens.headerStyle, color: tokens.chips?.color }
    : tokens.headerStyle;
  const headerTinted = Boolean(
    headerStyle?.backgroundColor || headerStyle?.backgroundImage || sweepBehindHeader,
  );
  const footerTinted = Boolean(tokens.footerStyle?.backgroundColor);

  const initials = student.full_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  const classLabel = student.class_name
    ? `${student.class_name}${student.section_name ? ` · ${student.section_name}` : ""}`
    : "—";

  const photoSize =
    PHOTO_SIZE_CLASSES[config.photo_size][config.photo_shape === "circle" ? "circle" : "frame"];
  const photo = (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden border border-border bg-muted",
        photoSize,
        PHOTO_SHAPE_CLASSES[config.photo_shape],
      )}
    >
      {student.photo_url ? (
        // Plain <img>, not next/image: the photo URL is school-supplied and
        // next/image refuses hosts it wasn't configured for.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={student.photo_url}
          alt={`Photo of ${student.full_name}`}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="text-2xl font-semibold text-muted-foreground">{initials}</span>
      )}
    </div>
  );

  const logo = school?.logoUrl ? (
    // Plain <img> for the same host-config reason as the student photo.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={school.logoUrl} alt="" className="size-7 shrink-0 rounded-sm object-contain" />
  ) : null;

  // Text colour on a tinted band is computed from the band's luminance rather
  // than fixed: a school picking lemon yellow must not get white-on-yellow
  // cards. The print stylesheet sets `print-color-adjust: exact`, which is
  // what makes filled bands survive printing.
  const centeredLogo = config.logo_position === "center";
  const schoolHeader = (
    <div className="relative border-b-2 border-foreground/80 px-3 py-1.5" style={headerStyle}>
      <div
        className={cn(
          "flex items-center gap-2",
          centeredLogo ? "justify-center text-center" : "text-start",
        )}
      >
        {config.logo_position !== "end" ? logo : null}
        <div className="min-w-0">
          <p className="truncate text-sm font-bold uppercase tracking-wide">
            {school?.name ?? "Student identity card"}
          </p>
          <p className={cn("text-[11px]", headerTinted ? "opacity-80" : "text-muted-foreground")}>
            {school ? `${school.code} · Student identity card` : " "}
          </p>
        </div>
        {config.logo_position === "end" && logo ? <span className="ms-auto">{logo}</span> : null}
      </div>
    </div>
  );

  /*
    The contact line is the half of an ID card that earns its place in a school
    bag: whoever finds the child or the card knows who to call. Which number is
    the principal's pick; `emergency` falls back to the guardian because a
    blank line on a lost card helps nobody. `mt-auto` pins it to the card's
    bottom edge — the card is a FIXED physical size, so the footer cannot just
    sit under the content.
  */
  const contactPhone =
    config.contact_number === "school"
      ? school?.phone
      : config.contact_number === "emergency"
        ? (student.emergency_contact_phone ?? student.guardian_phone)
        : student.guardian_phone;
  const contactFooter = (
    <div
      className={cn(
        "relative mt-auto border-t border-border px-3 py-1.5 text-center text-[10px] leading-tight",
        footerTinted ? "opacity-90" : "text-muted-foreground",
      )}
      style={tokens.footerStyle}
    >
      {config.contact_line.trim() ||
        (contactPhone ? `If found, please call ${contactPhone}` : "Issued by the school office")}
    </div>
  );

  // The 3mm accent rule of the "stripe" design, overlaid on the leading edge.
  const stripe = tokens.stripeColor ? (
    <div
      aria-hidden
      className="absolute inset-y-0 start-0 w-[3mm]"
      style={{ backgroundColor: tokens.stripeColor }}
    />
  ) : null;

  // The curved colour sweep (wave/tide). Purely decorative and BEHIND the
  // content (first in the stacking order, no z-index): on the leading edge
  // (or top, in portrait) for `start`, the trailing edge (or bottom) for
  // `end`. Two layers — a faint echo curve under the full-strength one —
  // give the layered swoosh of the sample cards.
  const sweep = (() => {
    const sw = tokens.sweep;
    if (!sw) return null;
    const atStart = (sw.edge ?? "start") === "start";
    const position = landscape
      ? cn("inset-y-0", atStart ? "start-0" : "end-0")
      : cn("inset-x-0", atStart ? "top-0" : "bottom-0");
    // The curve always faces INTO the card, so the rounded corners flip with
    // the edge: logical radius properties keep RTL correct for free.
    const radii = (main: boolean): React.CSSProperties => {
      const [a, b] = main ? ["60% 45%", "85% 70%"] : ["70% 55%", "60% 80%"];
      if (landscape) {
        return atStart
          ? { borderStartEndRadius: a, borderEndEndRadius: b }
          : { borderStartStartRadius: a, borderEndStartRadius: b };
      }
      return atStart
        ? { borderEndStartRadius: a, borderEndEndRadius: b }
        : { borderStartStartRadius: a, borderStartEndRadius: b };
    };
    return (
      <>
        <div
          aria-hidden
          className={cn("absolute opacity-25", position, landscape ? "w-[30mm]" : "h-[32mm]")}
          style={{ background: sw.background, ...radii(false) }}
        />
        <div
          aria-hidden
          className={cn("absolute", position, landscape ? "w-[24mm]" : "h-[26mm]")}
          style={{ background: sw.background, ...radii(true) }}
        />
      </>
    );
  })();
  const backdrop = <CardBackdrop backdrop={tokens.backdrop} />;

  /*
    Two spellings of a detail line, one semantic shape. Text-label rows for the
    quiet designs; for the print-shop designs (`tokens.chips`) the label
    becomes a little icon tag — pointed like the chevron sample cards or a
    round dot — and stays readable to screen readers via the sr-only label.
  */
  const chips = tokens.chips;
  const chipIcon: Record<string, React.ReactNode> = {
    "Admission no.": <Hash className="size-2.5" aria-hidden />,
    Class: <GraduationCap className="size-2.5" aria-hidden />,
    "Date of birth": <Cake className="size-2.5" aria-hidden />,
    Guardian: <UserRound className="size-2.5" aria-hidden />,
  };
  const field = (label: string, value: string) =>
    chips ? (
      <div className="flex items-center gap-1.5">
        <dt
          className={cn(
            "flex shrink-0 items-center",
            chips.shape === "arrow"
              ? "h-4 w-7 justify-start ps-1.5 [clip-path:polygon(0_0,72%_0,100%_50%,72%_100%,0_100%)]"
              : "size-4 justify-center rounded-full",
          )}
          style={{ backgroundColor: chips.background, color: chips.color }}
        >
          {chipIcon[label]}
          <span className="sr-only">{label}</span>
        </dt>
        <dd className="min-w-0 truncate font-medium">{value}</dd>
      </div>
    ) : (
      <div className="flex justify-between gap-2">
        <dt className="text-muted-foreground">{label}</dt>
        <dd className="truncate font-medium">{value}</dd>
      </div>
    );
  // Panel layouts print the class under the name (like the sample cards'
  // "Std.: 5th (B)"), so the list must not repeat it there.
  const classInList = !(landscape && tokens.panel);
  const detailFields = (
    <>
      {config.show_class && classInList ? field("Class", classLabel) : null}
      {config.show_date_of_birth
        ? field("Date of birth", student.date_of_birth ? formatDate(student.date_of_birth) : "—")
        : null}
      {config.show_guardian_name ? field("Guardian", student.guardian_name ?? "—") : null}
    </>
  );

  if (landscape) {
    if (tokens.panel) {
      // The panel layout of the sample cards: details down the leading side,
      // the photo riding a colour panel on the trailing edge — a wedge
      // pointing into the card (`chevron`) or a straight block (`panel`).
      // `photo_position` picks a side everywhere else; here the panel IS the
      // photo's place, so that knob does not apply.
      return (
        <div
          className="student-id-card relative mx-auto flex h-[53.98mm] w-[85.6mm] flex-col overflow-hidden rounded-[3.18mm] border-2 border-foreground/80 bg-card text-card-foreground"
          style={tokens.cardStyle}
        >
          {stripe}
          {backdrop}
          {schoolHeader}

          <div className="relative flex min-h-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col p-3 pe-1">
              <div className="min-w-0">
                <p className="truncate text-sm font-bold leading-tight">{student.full_name}</p>
                {config.show_class ? (
                  <p className="truncate text-[10px] text-muted-foreground">{classLabel}</p>
                ) : null}
              </div>

              <dl className="mt-1.5 space-y-1 text-[10px] leading-tight">
                {config.show_admission_number
                  ? field("Admission no.", student.admission_number)
                  : null}
                {detailFields}
              </dl>
            </div>

            <div
              className={cn(
                "flex w-[30mm] shrink-0 flex-col items-center justify-center p-2",
                tokens.panel.clip === "chevron" &&
                  "ps-5 [clip-path:polygon(32%_0,100%_0,100%_100%,32%_100%,0_50%)]",
              )}
              style={{ backgroundColor: tokens.panel.background, color: tokens.panel.color }}
            >
              {photo}
            </div>
          </div>

          {contactFooter}
        </div>
      );
    }

    // CR80 exactly: 85.60 × 53.98 mm.
    return (
      <div
        className="student-id-card relative mx-auto flex h-[53.98mm] w-[85.6mm] flex-col overflow-hidden rounded-[3.18mm] border-2 border-foreground/80 bg-card text-card-foreground"
        style={tokens.cardStyle}
      >
        {stripe}
        {sweep}
        {backdrop}
        {schoolHeader}

        <div
          className={cn(
            "relative flex min-h-0 gap-3 p-3",
            config.photo_position === "end" && "flex-row-reverse",
          )}
        >
          {photo}

          <dl className="min-w-0 flex-1 space-y-1 text-[11px] leading-tight">
            <div>
              <dt className="sr-only">Name</dt>
              <dd className="truncate text-sm font-bold">{student.full_name}</dd>
            </div>
            {config.show_admission_number ? (
              chips ? (
                field("Admission no.", student.admission_number)
              ) : (
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Admission no.</dt>
                  <dd className="font-medium tabular-nums">{student.admission_number}</dd>
                </div>
              )
            ) : null}
            {detailFields}
          </dl>
        </div>

        {contactFooter}
      </div>
    );
  }

  // The same CR80 card rotated: 53.98 × 85.60 mm, hanging from a lanyard.
  return (
    <div
      className="student-id-card relative mx-auto flex h-[85.6mm] w-[53.98mm] flex-col overflow-hidden rounded-[3.18mm] border-2 border-foreground/80 bg-card text-card-foreground"
      style={tokens.cardStyle}
    >
      {stripe}
      {sweep}
      {backdrop}
      {schoolHeader}

      {tokens.panel ? (
        // The panel designs keep their colour panel in portrait: it turns
        // under the header and carries the photo, the chevron's wedge pointing
        // down into the card the way the landscape one points inward.
        <div
          className={cn(
            "relative flex flex-col items-center px-3 pt-3",
            tokens.panel.clip === "chevron"
              ? "pb-6 [clip-path:polygon(0_0,100%_0,100%_calc(100%-4mm),50%_100%,0_calc(100%-4mm))]"
              : "pb-3",
          )}
          style={{ backgroundColor: tokens.panel.background, color: tokens.panel.color }}
        >
          {photo}
        </div>
      ) : null}

      <div
        className={cn(
          "relative flex min-h-0 flex-col items-center gap-1.5 px-3 text-center",
          tokens.panel ? "pt-1.5" : "pt-3",
        )}
      >
        {tokens.panel ? null : photo}
        <div className="min-w-0 max-w-full">
          <p className="truncate text-sm font-bold">{student.full_name}</p>
          {config.show_admission_number ? (
            <p className="text-[11px] tabular-nums text-muted-foreground">
              {student.admission_number}
            </p>
          ) : null}
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col px-3 pb-1 pt-2">
        <dl className="space-y-1 text-[11px] leading-tight">{detailFields}</dl>
      </div>

      {contactFooter}
    </div>
  );
}

/**
 * The card's BACK face, same CR80 dimensions and orientation as the front so
 * the two trim to one laminate. The back is the card's administrative half:
 * where the school is, what to do with a found card, when it was issued, and
 * the principal's signature line — the front stays the child's half.
 *
 * Designs brand the back through the header: panel designs fill it with the
 * panel colour, wave flows its sweep behind it (there is no photo back here
 * for a panel to carry), everything else reuses the front's header tokens.
 */
export function StudentCardBackView({
  student,
  school,
  config,
}: {
  student: StudentListRow;
  school: CardSchool | null;
  config: ResolvedCardDesign;
}) {
  const palette = resolvePalette(school);
  const tokens = designTokens(config.design, palette);
  const landscape = config.orientation === "landscape";

  // The back has no header band — the school is named on the front, and the
  // laminated sample backs open straight with the crest. Only the sweep's
  // edge still matters, for placing the decoration.
  const sweepAtTop = tokens.sweep ? (tokens.sweep.edge ?? "start") === "start" : false;
  const footerTinted = Boolean(tokens.footerStyle?.backgroundColor);

  const stripe = tokens.stripeColor ? (
    <div
      aria-hidden
      className="absolute inset-y-0 start-0 w-[3mm]"
      style={{ backgroundColor: tokens.stripeColor }}
    />
  ) : null;
  const sweep = tokens.sweep ? (
    <div
      aria-hidden
      className={cn("absolute inset-x-0 h-[14mm]", sweepAtTop ? "top-0" : "bottom-0")}
      style={{
        background: tokens.sweep.background,
        ...(sweepAtTop
          ? { borderEndStartRadius: "45% 40%", borderEndEndRadius: "70% 60%" }
          : { borderStartStartRadius: "45% 40%", borderStartEndRadius: "70% 60%" }),
      }}
    />
  ) : null;

  const addressLine = [school?.address, school?.city].filter(Boolean).join(", ");

  // The same "whose number" pick as the front footer, so the two faces never
  // tell a finder to call different people.
  const contactPhone =
    (config.contact_number === "school"
      ? school?.phone
      : config.contact_number === "emergency"
        ? (student.emergency_contact_phone ?? student.guardian_phone)
        : student.guardian_phone) ?? school?.phone;

  /*
    The QR lives on the BACK, like a bank card's machine-readable half. It
    carries the identification itself — name, roll number, class — not a link:
    any phone camera then identifies the card's owner offline, with no app, no
    account and no server. Nothing beyond what the card already prints goes
    in, so the QR never leaks more than the card does.
  */
  const classLabel = student.class_name
    ? `${student.class_name}${student.section_name ? ` · ${student.section_name}` : ""}`
    : "—";
  const qrText = [
    `Name: ${student.full_name}`,
    `Roll no: ${student.admission_number}`,
    `Class: ${classLabel}`,
    ...(school ? [`School: ${school.name} (${school.code})`] : []),
  ].join("\n");
  const qr = config.show_qr ? (
    // Always on white with a quiet zone: a themed or transparent background is
    // the classic way to produce a QR that scans on screen and fails on paper.
    <div className="shrink-0 rounded-sm bg-white p-0.5">
      <QRCodeSVG value={qrText} size={landscape ? 44 : 52} marginSize={1} level="M" />
    </div>
  ) : null;

  return (
    <div
      className={cn(
        "student-id-card relative mx-auto flex flex-col overflow-hidden rounded-[3.18mm] border-2 border-foreground/80 bg-card text-card-foreground",
        landscape ? "h-[53.98mm] w-[85.6mm]" : "h-[85.6mm] w-[53.98mm]",
      )}
      style={tokens.cardStyle}
    >
      {stripe}
      {sweep}
      <CardBackdrop backdrop={tokens.backdrop} />

      {/* No header, no crest: the school is identified on the front, and the
          back keeps its 86mm for the rules, the office block and the QR. */}
      <div className="relative flex min-h-0 flex-1 flex-col gap-1.5 overflow-hidden px-3 py-2 text-[10px] leading-snug">
        {config.rules.length > 0 ? (
          // The school's conduct lines, numbered like the sample card's back.
          <ol className="list-decimal space-y-0.5 ps-3.5 text-[9px] font-medium leading-tight">
            {config.rules.map((rule, index) => (
              <li key={index}>{rule}</li>
            ))}
          </ol>
        ) : null}

        {addressLine || school?.phone || school?.email ? (
          <div className="space-y-0.5">
            <p className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
              School office
            </p>
            {addressLine ? <p>{addressLine}</p> : null}
            {school?.phone ? <p>{school.phone}</p> : null}
            {school?.email ? <p className="truncate">{school.email}</p> : null}
          </div>
        ) : null}

        {/* Custom wording verbatim when the school typed one; otherwise the
            standard line, composed fresh from the current name and number. */}
        <p className="whitespace-pre-line text-muted-foreground">
          {config.found_notice.trim() ||
            `This card identifies a student of ${school?.name ?? "the school"} and remains school property. If found, please return it to the school office${contactPhone ? ` or call ${contactPhone}` : ""}.`}
        </p>

        {/* QR and signature over the validity dates: the machine-readable
            corner and the human one. `mt-auto` pins the row to the bottom
            edge. Expiry is enrolment + one year — a session card, reissued
            yearly like the sample's 2025-26. */}
        <div className="mt-auto flex items-end justify-between gap-3 pt-1">
          <div className="flex flex-col gap-0.5">
            {qr}
            {config.show_validity && student.enrolled_on ? (
              <div className="text-[9px] leading-tight text-muted-foreground">
                <p>Issued {formatDate(student.enrolled_on)}</p>
                <p>Expires {formatDate(addOneYear(student.enrolled_on))}</p>
              </div>
            ) : null}
          </div>
          <div className="text-center">
            <div className="mb-0.5 w-24 border-b border-foreground/70" />
            <p className="text-[9px] text-muted-foreground">Principal</p>
          </div>
        </div>
      </div>

      <div
        className={cn(
          "relative border-t border-border px-3 py-1 text-center text-[9px] leading-tight",
          footerTinted ? "opacity-90" : "text-muted-foreground",
        )}
        style={tokens.footerStyle}
      >
        {`Card ${student.admission_number}${school ? ` · ${school.code}` : ""}`}
      </div>
    </div>
  );
}
