import { buttonVariants } from "@heroui/styles";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { LABELS, type MarketingCopy } from "@/components/marketing/copy";
import { Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { SectionLabel } from "@/components/marketing/section";
import { ParticleField } from "@/components/marketing/three/particle-field";
import { demoUrl } from "@/lib/site";

/**
 * The closing call to action every public page ends on: the one blue card, with
 * white points rolling under it. Its second button books a free demo when the
 * site has a contact, else shows pricing.
 */
export function CtaBand({ copy }: { copy: MarketingCopy }) {
  const demoHref = demoUrl(copy.common.demoMessage);
  return (
    <section className="mk-section mk-cta-wrap">
      <div className="mk-container">
        <div className="mk-blue mk-cta">
          <ParticleField tone="blue" />
          <div className="mk-cta__glow" aria-hidden />
          <Stagger className="relative flex flex-col items-center text-center" gap={0.1}>
            <StaggerItem>
              <SectionLabel label={LABELS.start} />
            </StaggerItem>
            <StaggerItem>
              <h2 className="mk-title--cta mt-6 font-mk-display text-[clamp(2.4rem,6vw,4.6rem)] leading-[1.02] font-extrabold tracking-[-0.04em] text-balance">
                {copy.home.cta.title}
              </h2>
            </StaggerItem>
            <StaggerItem>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-pretty text-mk-muted">{copy.home.cta.body}</p>
            </StaggerItem>
            <StaggerItem className="mt-9 flex flex-wrap justify-center gap-3">
              <Link href="/signup" className={buttonVariants({ variant: "primary", size: "lg", className: "mk-shine" })}>
                {copy.common.startFree}
                <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
              </Link>
              {demoHref ? (
                <a
                  href={demoHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonVariants({ variant: "outline", size: "lg" })}
                >
                  {copy.common.bookDemo}
                </a>
              ) : (
                <Link href="/pricing" className={buttonVariants({ variant: "outline", size: "lg" })}>
                  {copy.common.seePricing}
                </Link>
              )}
            </StaggerItem>
            <StaggerItem>
              <p className="mt-4 text-sm text-mk-muted">{copy.common.freeNote}</p>
            </StaggerItem>
          </Stagger>
        </div>
      </div>
    </section>
  );
}
