import type { Metadata, Route } from "next";
import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowRight,
  BookOpenCheck,
  Building2,
  Calculator,
  Check,
  Database,
  Gift,
  History,
  KeyRound,
  Languages,
  LockOpen,
  MessageCircle,
  MonitorSmartphone,
  Palette,
  ShieldCheck,
  UserCheck,
  Users,
  Zap,
} from "lucide-react";

import { CampusDemo } from "@/components/marketing/campus-demo";
import { ChallanDemo } from "@/components/marketing/challan-demo";
import { LABELS, getCopy, type Pair } from "@/components/marketing/copy";
import { CtaBand } from "@/components/marketing/cta-band";
import { DiaryDemo } from "@/components/marketing/diary-demo";
import { Faq } from "@/components/marketing/faq";
import { ALSO_INCLUDED_ICONS, featurePath, getFeatures, type FeatureSlug } from "@/components/marketing/features";
import { Hero } from "@/components/marketing/hero";
import { HeroDashboard } from "@/components/marketing/home/hero-dashboard";
import { ModuleHub } from "@/components/marketing/home/module-hub";
import { ProductTour } from "@/components/marketing/home/product-tour";
import { InView } from "@/components/marketing/in-view";
import { JsonLd } from "@/components/marketing/json-ld";
import { Marquee } from "@/components/marketing/marquee";
import { CountUp } from "@/components/marketing/motion/count-up";
import { Reveal, Stagger, StaggerItem } from "@/components/marketing/motion/reveal";
import { Spotlight } from "@/components/marketing/motion/spotlight";
import { PagesDemo } from "@/components/marketing/pages-demo";
import { RegisterDemo } from "@/components/marketing/register-demo";
import { RtlDemo } from "@/components/marketing/rtl-demo";
import { Section, SectionHeading, SectionLabel } from "@/components/marketing/section";
import { getLocale } from "@/lib/i18n/server";
import { SITE_NAME, SITE_URL, pageMetadata } from "@/lib/site";
import { cn } from "@/lib/utils";

export async function generateMetadata(): Promise<Metadata> {
  const copy = getCopy(await getLocale());
  return pageMetadata({ description: copy.home.metaDescription, path: "/" });
}

/** Stagger index for the CSS-animated `.mk-flow` steps. */
const at = (i: number) => ({ "--i": i }) as CSSProperties;

/** Where each of `home.ai.flows` is explained in full, in the same order. */
const AI_FLOW_SLUGS: FeatureSlug[] = [
  "whatsapp-diary",
  "whatsapp-attendance",
  "test-paper-generator",
  "test-paper-generator",
];

/** The platform grid's order: the diary card is the wide one. */
const PLATFORM: FeatureSlug[] = [
  "whatsapp-diary",
  "whatsapp-attendance",
  "fee-management",
  "test-paper-generator",
  "attendance",
  "multi-campus",
  "urdu",
];

const SECURITY_ICONS = [MonitorSmartphone, Database, MessageCircle, KeyRound, History];
const ROLE_ICONS = [Building2, BookOpenCheck, Calculator, Users];
const WHY_ICONS = [Gift, Zap, MonitorSmartphone, Palette, Building2, ShieldCheck, UserCheck, LockOpen, Languages];

/** The overview's link into a feature's own page. */
function MoreLink({ slug, children, className }: { slug: FeatureSlug; children: string; className?: string }) {
  return (
    <Link href={featurePath(slug) as Route} className={`mk-textlink ${className ?? ""}`}>
      {children}
      <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
    </Link>
  );
}

/** A blue tick beside a fact. */
function Tick() {
  return (
    <span className="mk-tick" aria-hidden>
      <Check className="size-3" strokeWidth={3} />
    </span>
  );
}

/**
 * One tab of the tour: what the part does, beside (or above, for the wide ones)
 * its illustrated demo.
 */
function TourPanel({
  title,
  lede,
  facts,
  extra,
  slug,
  more,
  demo,
  wide = false,
}: {
  title: string;
  lede: string;
  facts?: Pair[];
  extra?: ReactNode;
  slug: FeatureSlug;
  more: string;
  demo: ReactNode;
  wide?: boolean;
}) {
  const text = (
    <>
      <h3 className="font-mk-display text-[clamp(1.6rem,3vw,2.2rem)] leading-tight font-extrabold tracking-[-0.03em] text-balance">
        {title}
      </h3>
      <p className="mt-4 leading-relaxed text-pretty text-mk-muted">{lede}</p>
    </>
  );
  const list = facts ? (
    <ul className="grid gap-4">
      {facts.slice(0, 3).map(([factTitle, body]) => (
        <li key={factTitle} className="flex gap-3">
          <Tick />
          <div>
            <p className="font-semibold">{factTitle}</p>
            <p className="mt-0.5 text-sm leading-relaxed text-pretty text-mk-muted">{body}</p>
          </div>
        </li>
      ))}
    </ul>
  ) : null;

  if (wide) {
    return (
      <div className="mk-tour">
        <div className="grid gap-8 lg:grid-cols-2 lg:gap-12">
          <div>
            {text}
            {extra}
            <MoreLink slug={slug} className="mt-6">
              {more}
            </MoreLink>
          </div>
          {list}
        </div>
        <div className="mt-10 min-w-0">{demo}</div>
      </div>
    );
  }

  return (
    <div className="mk-tour grid items-center gap-10 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-14">
      <div>
        {text}
        {extra}
        {list ? <div className="mt-7">{list}</div> : null}
        <MoreLink slug={slug} className="mt-8">
          {more}
        </MoreLink>
      </div>
      <div className="min-w-0">{demo}</div>
    </div>
  );
}

export default async function LandingPage() {
  const locale = await getLocale();
  const copy = getCopy(locale);
  const { home, common } = copy;
  const features = getFeatures(locale);
  const feature = (slug: FeatureSlug) => features.find((f) => f.slug === slug)!;
  const diary = feature("whatsapp-diary");

  return (
    <div className="mk-heroui">
      {/* No aggregateRating or reviews: there are none to cite yet, and invented
          ones are exactly what search engines penalise. */}
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareApplication",
          name: SITE_NAME,
          url: SITE_URL,
          applicationCategory: "BusinessApplication",
          operatingSystem: "Web",
          inLanguage: ["en", "ur"],
          description: home.metaDescription,
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: home.faqs.map(([q, a]) => ({
            "@type": "Question",
            name: q,
            acceptedAnswer: { "@type": "Answer", text: a },
          })),
        }}
      />

      {/* ── Hero: the dashboard ───────────────────────────────────────── */}
      <Hero
        label={LABELS.audience}
        title={
          <>
            {home.hero.title.before}
            <span className="mk-hero__em">{home.hero.title.em}</span>
            {home.hero.title.after}
          </>
        }
        lede={home.hero.lede}
        common={common}
        points={home.hero.points}
        demoSide
        demo={<HeroDashboard copy={home.dashboard} />}
      />

      <Marquee label={home.ticker} />

      {/* ── One platform: every module ───────────────────────────────── */}
      <Section id="platform">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <SectionHeading label={LABELS.platform} title={home.platform.title} lede={home.platform.lede} />
          <Reveal className="shrink-0">
            <Link href="/features" className="mk-textlink">
              {home.platform.more}
              <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
            </Link>
          </Reveal>
        </div>

        <Stagger as="ul" className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" gap={0.06}>
          {PLATFORM.map((slug, i) => {
            const item = feature(slug);
            const wide = i === 0;
            return (
              <StaggerItem as="li" key={slug} className={cn(wide && "sm:col-span-2")}>
                <Spotlight className="h-full">
                  <Link href={featurePath(slug) as Route} className={cn("mk-module", wide && "mk-module--wide")}>
                    <item.icon className="mk-module__mark" aria-hidden />
                    <span className="mk-module__icon">
                      <item.icon className="size-5" aria-hidden />
                    </span>
                    <span className="mt-5 font-mk-display text-xl font-bold tracking-[-0.02em]">{item.nav}</span>
                    <span className="mt-2 leading-relaxed text-pretty text-mk-muted">{item.summary}</span>
                    <span className="mk-module__more">
                      {common.readMore}
                      <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
                    </span>
                  </Link>
                </Spotlight>
              </StaggerItem>
            );
          })}
          <StaggerItem as="li" className="sm:col-span-2 lg:col-span-4">
            <div className="mk-also">
              <p className="font-mk-display text-lg font-bold">{common.alsoIncluded}</p>
              <ul className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {copy.alsoIncluded.map((label, i) => {
                  const Icon = ALSO_INCLUDED_ICONS[i]!;
                  return (
                    <li key={label} className="flex items-center gap-3 text-[0.95rem]">
                      <Icon className="size-4.5 shrink-0 text-mk-ink" aria-hidden />
                      <span>{label}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </StaggerItem>
        </Stagger>
      </Section>

      {/* ── AI: each workflow as what staff send and what comes back ────── */}
      <Section id="ai" tone="night" className="mk-ai">
        <SectionHeading label={LABELS.ai} title={home.ai.title} lede={home.ai.lede} />
        <Stagger as="ul" className="mt-12 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {home.ai.flows.map(([title, send, result], i) => (
            <StaggerItem as="li" key={title}>
              <Spotlight className="h-full">
                <div className="mk-flowcard">
                  <span className="mk-flowcard__no">0{i + 1}</span>
                  <h3 className="font-mk-display text-xl font-bold tracking-[-0.01em]">{title}</h3>
                  <p className="mt-5 text-xs font-semibold tracking-wide text-mk-muted uppercase">{home.ai.send}</p>
                  <p className="mt-2 rounded-2xl rounded-ss-md border border-mk-line bg-mk-paper px-4 py-3 font-medium">
                    {send}
                  </p>
                  <span className="mk-flowcard__arrow" aria-hidden>
                    <ArrowDown className="size-4" />
                  </span>
                  <p className="text-xs font-semibold tracking-wide text-mk-muted uppercase">{home.ai.result}</p>
                  <p className="mt-2 flex-1 leading-relaxed text-pretty">{result}</p>
                  <MoreLink slug={AI_FLOW_SLUGS[i]!} className="mt-6">
                    {common.readMore}
                  </MoreLink>
                </div>
              </Spotlight>
            </StaggerItem>
          ))}
        </Stagger>
      </Section>

      {/* ── The tour: every part, with its demo ───────────────────────── */}
      <Section id="tour" tone="fog">
        <SectionHeading label={LABELS.tour} title={home.tour.title} lede={home.tour.lede} center />
        <Reveal className="mt-12">
          <ProductTour
            label={home.tour.title}
            tabs={[
              {
                id: "diary",
                label: diary.nav,
                icon: "whatsapp-diary",
                panel: (
                  <TourPanel
                    title={diary.h1}
                    lede={diary.lede}
                    facts={diary.details}
                    slug="whatsapp-diary"
                    more={common.readMore}
                    demo={
                      <DiaryDemo
                        steps={home.steps}
                        pauseLabel={home.pause}
                        playLabel={home.play}
                        description={home.demoDescription}
                      />
                    }
                  />
                ),
              },
              {
                id: "fees",
                label: feature("fee-management").nav,
                icon: "fee-management",
                panel: (
                  <TourPanel
                    wide
                    title={home.fees.title}
                    lede={home.fees.lede}
                    facts={home.fees.facts}
                    slug="fee-management"
                    more={home.fees.more}
                    demo={<ChallanDemo description={copy.demos.challan} />}
                  />
                ),
              },
              {
                id: "attendance",
                label: feature("attendance").nav,
                icon: "attendance",
                panel: (
                  <TourPanel
                    title={home.attendance.title}
                    lede={home.attendance.lede}
                    facts={home.attendance.facts}
                    slug="attendance"
                    more={home.attendance.more}
                    demo={<RegisterDemo description={copy.demos.register} />}
                  />
                ),
              },
              {
                id: "papers",
                label: feature("test-paper-generator").nav,
                icon: "test-paper-generator",
                panel: (
                  <TourPanel
                    title={home.papers.title}
                    lede={home.papers.lede}
                    slug="test-paper-generator"
                    more={home.papers.more}
                    extra={
                      <div className="mt-6">
                        <p className="leading-relaxed text-mk-muted">{home.papers.recipeLede}</p>
                        <div className="mt-4 flex flex-wrap items-center gap-2">
                          {home.papers.recipe.map((item) => (
                            <span key={item} className="rounded-full border border-mk-line px-3.5 py-1.5 text-sm">
                              {item}
                            </span>
                          ))}
                          <span className="rounded-full bg-mk-text px-3.5 py-1.5 text-sm font-semibold text-mk-paper">
                            {home.papers.draft}
                          </span>
                        </div>
                      </div>
                    }
                    demo={
                      <div className="rounded-3xl border border-mk-line bg-mk-fog p-3 sm:p-6">
                        <PagesDemo description={copy.demos.pages} />
                      </div>
                    }
                  />
                ),
              },
              {
                id: "campuses",
                label: feature("multi-campus").nav,
                icon: "multi-campus",
                panel: (
                  <TourPanel
                    wide
                    title={home.campuses.title}
                    lede={home.campuses.lede}
                    facts={home.campuses.pillars}
                    slug="multi-campus"
                    more={home.campuses.more}
                    demo={<CampusDemo description={copy.demos.campus} />}
                  />
                ),
              },
              {
                id: "urdu",
                label: feature("urdu").nav,
                icon: "urdu",
                panel: (
                  <TourPanel
                    title={home.urdu.title}
                    lede={home.urdu.lede}
                    facts={feature("urdu").details}
                    slug="urdu"
                    more={home.urdu.more}
                    demo={<RtlDemo locale={locale} />}
                  />
                ),
              },
            ]}
          />
        </Reveal>
      </Section>

      {/* ── Online, secure, joined up ─────────────────────────────────── */}
      <Section id="security">
        <div className="grid items-center gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-16">
          <div>
            <SectionHeading label={LABELS.security} title={home.security.title} lede={home.security.lede} />
            <Stagger as="dl" className="mt-10 grid gap-6">
              {home.security.points.map(([title, body], i) => {
                const Icon = SECURITY_ICONS[i]!;
                return (
                  <StaggerItem key={title} className="flex gap-4">
                    <span className="mk-iconbox">
                      <Icon className="size-4.5" aria-hidden />
                    </span>
                    <div>
                      <dt className="font-semibold">{title}</dt>
                      <dd className="mt-1 leading-relaxed text-pretty text-mk-muted">{body}</dd>
                    </div>
                  </StaggerItem>
                );
              })}
            </Stagger>
          </div>
          <ModuleHub name={locale === "ur" ? "اسکول یار" : SITE_NAME} nodes={home.security.hub} />
        </div>
      </Section>

      {/* ── Everyone in the school ────────────────────────────────────── */}
      <Section id="roles" tone="night">
        <SectionHeading label={LABELS.roles} title={home.roles.title} lede={home.roles.lede} />
        <Stagger as="ul" className="mt-12 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {home.roles.items.map((role, i) => {
            const Icon = ROLE_ICONS[i]!;
            return (
              <StaggerItem as="li" key={role.title}>
                <Spotlight className="h-full">
                  <div className="mk-role">
                    <span className="mk-role__icon">
                      <Icon className="size-5" aria-hidden />
                    </span>
                    <h3 className="mt-5 font-mk-display text-xl font-bold">{role.title}</h3>
                    <p className="mt-2 leading-relaxed text-pretty text-mk-muted">{role.body}</p>
                    <ul className="mt-6 grid gap-3 border-t border-mk-line pt-6 text-[0.95rem]">
                      {role.points.map((point) => (
                        <li key={point} className="flex gap-3">
                          <Tick />
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </Spotlight>
              </StaggerItem>
            );
          })}
        </Stagger>
      </Section>

      {/* ── In numbers: facts about the product ───────────────────────── */}
      <Section className="mk-numbers">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.6fr)_minmax(0,1.4fr)] lg:items-center">
          <SectionHeading label={LABELS.numbers} title={home.numbers.title} />
          <Stagger as="dl" className="grid grid-cols-2 gap-px overflow-hidden rounded-3xl border border-mk-line bg-mk-line lg:grid-cols-4">
            {home.numbers.items.map(([value, label]) => (
              <StaggerItem key={label} className="flex flex-col-reverse bg-mk-paper p-6 sm:p-8">
                <dt className="mt-2 text-sm leading-snug text-pretty text-mk-muted">{label}</dt>
                <dd className="mk-number">
                  <CountUp value={value} />
                </dd>
              </StaggerItem>
            ))}
          </Stagger>
        </div>
      </Section>

      {/* ── Why schools choose it ─────────────────────────────────────── */}
      <Section id="why" tone="fog">
        <SectionHeading label={LABELS.why} title={home.why.title} lede={home.why.lede} center />
        <Stagger as="ul" className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" gap={0.05}>
          {home.why.items.map(([title, body], i) => {
            const Icon = WHY_ICONS[i]!;
            return (
              <StaggerItem as="li" key={title}>
                <Spotlight className="h-full" lift={-3}>
                  <div className="mk-why">
                    <span className="mk-iconbox">
                      <Icon className="size-4.5" aria-hidden />
                    </span>
                    <div>
                      <h3 className="font-semibold">{title}</h3>
                      <p className="mt-1.5 leading-relaxed text-pretty text-mk-muted">{body}</p>
                    </div>
                  </div>
                </Spotlight>
              </StaggerItem>
            );
          })}
        </Stagger>
      </Section>

      {/* ── Getting started: a numbered sequence ─────────────────────── */}
      <Section id="start">
        <SectionHeading label={LABELS.begin} title={home.start.title} />
        <InView threshold={0.3}>
          <ol className="mk-flow mt-14" style={{ "--n": home.start.steps.length } as CSSProperties}>
            {home.start.steps.map(([title, body], i) => (
              <li key={title} className="mk-flow__step" style={at(i)}>
                <span className="mk-flow__no" style={at(i)} aria-hidden>
                  {i + 1}
                </span>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="mt-2 leading-relaxed text-pretty text-mk-muted">{body}</p>
              </li>
            ))}
          </ol>
        </InView>
      </Section>

      {/* ── Our name ──────────────────────────────────────────────────── */}
      <Section tone="night">
        <InView threshold={0.4} className="grid items-center gap-6 lg:grid-cols-2 lg:gap-16">
          {locale === "ur" ? (
            <p className="mk-yaar__word mk-ur-deco" lang="ur" aria-hidden>
              یار
            </p>
          ) : (
            <p className="mk-yaar__word" lang="en" aria-hidden>
              Yaar<span>.</span>
            </p>
          )}
          <Stagger gap={0.1}>
            <StaggerItem>
              <SectionLabel label={LABELS.name} />
            </StaggerItem>
            <StaggerItem>
              <h2 className="mk-title--section mt-5 font-mk-display text-[clamp(2.4rem,5vw,4rem)] leading-[1.02] font-extrabold tracking-[-0.04em]">
                {home.yaar.title}
              </h2>
            </StaggerItem>
            <StaggerItem>
              <p className="mt-6 max-w-lg text-lg leading-relaxed text-pretty text-mk-muted">{home.yaar.body}</p>
            </StaggerItem>
          </Stagger>
        </InView>
      </Section>

      {/* ── Questions ─────────────────────────────────────────────────── */}
      <Section id="questions">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
          <SectionHeading
            label={LABELS.questions}
            title={common.questionsTitle}
            lede={
              <>
                {common.questionsLede.before}
                <Link href="/signup" className="mk-textlink">
                  {common.questionsLede.link}
                </Link>
                {common.questionsLede.after}
              </>
            }
          />
          <Reveal>
            <Faq items={home.faqs} />
          </Reveal>
        </div>
      </Section>

      <CtaBand copy={copy} />
    </div>
  );
}
