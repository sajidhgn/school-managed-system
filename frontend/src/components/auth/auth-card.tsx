import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { getCopy } from "@/components/marketing/copy";
import { LogoMark } from "@/components/marketing/logo";
import { Reveal, Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { ParticleField } from "@/components/marketing/three/particle-field";
import { getLocale } from "@/lib/i18n/server";

/**
 * The frame every auth screen sits in: login, signup, reset, invitation accept.
 *
 * A shared shell rather than per-page markup so the six of them cannot drift apart
 * in spacing, heading weight or footer placement — differences a user notices as
 * "this page feels different" without being able to say why.
 *
 * From `lg` the form sits beside a black panel in the public site's style: points
 * rolling in three.js, and what SchoolYar is in three lines. The form itself keeps
 * the tenant panel's components, so signing in looks like the product it opens.
 */
export async function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const locale = await getLocale();
  const { authAside } = getCopy(locale);

  return (
    <div className="mk-auth">
      <div className="mk-auth__form">
        <Reveal className="w-full max-w-md" y={18}>
          <div className="rounded-2xl border border-border bg-card p-8 shadow-[0_30px_60px_-40px_rgb(10_12_16/0.45)]">
            <h1 className="font-mk-display text-2xl font-extrabold tracking-[-0.03em]">{title}</h1>
            {description ? (
              <p className="mt-1.5 text-sm text-muted-foreground text-pretty">{description}</p>
            ) : null}
            <div className="mt-6">{children}</div>
          </div>
          {footer ? <p className="mt-5 text-center text-sm text-muted-foreground">{footer}</p> : null}
        </Reveal>
      </div>

      <aside className="mk-night mk-auth__aside">
        <ParticleField />
        <div className="mk-hero__glow" aria-hidden />
        <Stagger className="relative max-w-md" gap={0.1} delay={0.15}>
          <StaggerItem>
            <LogoMark className="size-11" />
          </StaggerItem>
          <StaggerItem>
            <p className="mt-8 font-mk-display text-[2.2rem] leading-[1.08] font-extrabold tracking-[-0.035em] text-balance">
              {authAside.title}
            </p>
          </StaggerItem>
          <StaggerItem>
            <p className="mt-4 text-lg leading-relaxed text-pretty text-mk-muted">{authAside.body}</p>
          </StaggerItem>
          <StaggerItem as="ul" className="mt-8 grid gap-3">
            {authAside.points.map((point) => (
              <li key={point} className="flex items-center gap-3">
                <span className="mk-hero__tick" aria-hidden>
                  <Check className="size-3" strokeWidth={3} />
                </span>
                {point}
              </li>
            ))}
          </StaggerItem>
        </Stagger>
      </aside>
    </div>
  );
}

/** Kept importable from here for the server pages; client modules import auth-link.tsx. */
export { AuthLink } from "./auth-link";
