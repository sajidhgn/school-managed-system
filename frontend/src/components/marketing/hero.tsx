import { buttonVariants } from "@heroui/styles";
import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import type { BiLabelText, MarketingCopy } from "@/components/marketing/copy";
import { SectionLabel } from "@/components/marketing/section";
import { ParticleField } from "@/components/marketing/three/particle-field";
import { demoUrl } from "@/lib/site";
import { cn } from "@/lib/utils";

const at = (i: number) => ({ "--i": i }) as CSSProperties;

/**
 * The black opening band every public page starts with: a three.js sea of points
 * under a blue glow, then the label, the headline, the two calls to action and the
 * page's illustration. The second button books a free demo when the site has a
 * contact (`demoUrl`), else shows pricing.
 *
 * The text animates in with CSS alone, so the headline is visible before the page
 * hydrates and before three.js has even loaded.
 */
export function Hero({
  label,
  title,
  lede,
  common,
  breadcrumbs,
  demo,
  demoSide = false,
  center = false,
  points,
  actions = true,
  after,
}: {
  label: BiLabelText;
  title: ReactNode;
  lede: string;
  common: MarketingCopy["common"];
  breadcrumbs?: ReactNode;
  demo?: ReactNode;
  /** Beside the text on wide screens, rather than below it. */
  demoSide?: boolean;
  /** Centred text, for pages whose content below carries the weight. */
  center?: boolean;
  /** Short facts under the buttons; without them, the free-plan note. */
  points?: string[];
  /** The two buttons and the note under them; off where the page itself is the next step. */
  actions?: boolean;
  after?: ReactNode;
}) {
  const demoHref = demoUrl(common.demoMessage);
  return (
    <section className={cn("mk-night mk-hero", center && "mk-hero--center")}>
      <ParticleField />
      <div className="mk-hero__glow" aria-hidden />
      <div className="mk-hero__grid" aria-hidden />

      <div className="mk-container relative">
        {breadcrumbs}
        <div
          className={cn(
            demoSide && "grid items-center gap-14 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:gap-12",
          )}
        >
          <div className={cn(!demoSide && "max-w-4xl", center && "mx-auto text-center")}>
            <SectionLabel label={label} className="mk-rise" style={at(0)} />
            <h1
              className={cn(
                "mk-rise mk-title--hero mt-6 font-mk-display font-extrabold tracking-[-0.04em] text-balance",
                demoSide ? "text-[clamp(2.5rem,4.6vw,4.25rem)]" : "text-[clamp(2.6rem,6vw,5rem)]",
                // After the size: tailwind-merge drops a leading-* that precedes a text-* size.
                "leading-[1.04]",
              )}
              style={at(1)}
            >
              {title}
            </h1>
            <p
              className={cn(
                "mk-rise mt-6 max-w-2xl text-lg leading-relaxed text-pretty text-mk-muted sm:text-[1.15rem]",
                center && "mx-auto",
              )}
              style={at(2)}
            >
              {lede}
            </p>
            {actions ? (
              <>
                <div className={cn("mk-rise mt-9 flex flex-wrap gap-3", center && "justify-center")} style={at(3)}>
                  <Link
                    href="/signup"
                    className={buttonVariants({ variant: "primary", size: "lg", className: "mk-shine" })}
                  >
                    {common.startFree}
                    <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
                  </Link>
                  {demoHref ? (
                    <a
                      href={demoHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={buttonVariants({ variant: "outline", size: "lg" })}
                    >
                      {common.bookDemo}
                    </a>
                  ) : (
                    <Link href="/pricing" className={buttonVariants({ variant: "outline", size: "lg" })}>
                      {common.seePricing}
                    </Link>
                  )}
                </div>
                {points ? (
                  <ul
                    className={cn(
                      "mk-rise mt-7 flex flex-wrap gap-x-5 gap-y-2.5 text-sm text-mk-muted",
                      center && "justify-center",
                    )}
                    style={at(4)}
                  >
                    {points.map((point) => (
                      <li key={point} className="inline-flex items-center gap-2">
                        <span className="mk-hero__tick" aria-hidden>
                          <Check className="size-3" strokeWidth={3} />
                        </span>
                        {point}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mk-rise mt-4 text-sm text-mk-muted" style={at(4)}>
                    {common.freeNote}
                  </p>
                )}
              </>
            ) : null}
            {after}
          </div>
          {demoSide ? demo : null}
        </div>
        {!demoSide && demo ? (
          <div className="mk-rise mt-16" style={at(5)}>
            {demo}
          </div>
        ) : null}
      </div>
    </section>
  );
}
