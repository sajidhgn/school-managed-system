import type { CSSProperties, ReactNode } from "react";

import type { BiLabelText } from "@/components/marketing/copy";
import { Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { getLocale } from "@/lib/i18n/server";
import { cn } from "@/lib/utils";

type Tone = "paper" | "fog" | "night" | "blue";

const TONE_CLASS: Record<Tone, string | undefined> = {
  paper: undefined,
  fog: "mk-fog",
  night: "mk-night",
  blue: "mk-blue",
};

/**
 * One band of a public page. The tone re-points the colour tokens (see
 * marketing.css), so anything inside reads correctly on white, fog-gray, black
 * or blue without a variant of its own.
 */
export function Section({
  id,
  tone = "paper",
  className,
  children,
}: {
  id?: string;
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={cn("mk-section", TONE_CLASS[tone], className)}>
      <div className="mk-container">{children}</div>
    </section>
  );
}

/**
 * The small pill above a section heading, in the visitor's language only: an
 * English page shows no Urdu and an Urdu page no English.
 */
export async function SectionLabel({
  label,
  className,
  style,
}: {
  label: BiLabelText;
  className?: string;
  style?: CSSProperties;
}) {
  const locale = await getLocale();
  return (
    <p className={cn("mk-label", className)} style={style}>
      <span className="mk-label__dot" aria-hidden />
      <span>{label[locale]}</span>
    </p>
  );
}

/** A section's label, heading and optional lede, arriving one after another. */
export function SectionHeading({
  label,
  title,
  lede,
  className,
  center = false,
}: {
  label?: BiLabelText;
  title: ReactNode;
  lede?: ReactNode;
  className?: string;
  center?: boolean;
}) {
  return (
    <Stagger className={cn("max-w-3xl", center && "mx-auto text-center", className)} gap={0.1}>
      {label ? (
        <StaggerItem>
          <SectionLabel label={label} />
        </StaggerItem>
      ) : null}
      <StaggerItem>
        <h2
          className={cn(
            "mk-title--section font-mk-display text-[clamp(2rem,4vw,3.25rem)] leading-[1.06] font-extrabold tracking-[-0.035em] text-balance",
            label && "mt-5",
          )}
        >
          {title}
        </h2>
      </StaggerItem>
      {lede ? (
        <StaggerItem>
          <p className={cn("mt-5 max-w-2xl text-lg leading-relaxed text-pretty text-mk-muted", center && "mx-auto")}>
            {lede}
          </p>
        </StaggerItem>
      ) : null}
    </Stagger>
  );
}
