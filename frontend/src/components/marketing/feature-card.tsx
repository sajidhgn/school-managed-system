import type { Route } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { featurePath, type Feature } from "@/components/marketing/features";
import { Spotlight } from "@/components/marketing/motion/spotlight";

/** A feature's card, linking to its page. On /features and under each feature page's "See also". */
export function FeatureCard({ feature, more }: { feature: Feature; more: string }) {
  return (
    <Spotlight className="h-full">
      <Link href={featurePath(feature.slug) as Route} className="mk-module">
        <feature.icon className="mk-module__mark" aria-hidden />
        <span className="mk-module__icon">
          <feature.icon className="size-5" aria-hidden />
        </span>
        <span className="mt-5 font-mk-display text-xl font-bold tracking-[-0.02em]">{feature.nav}</span>
        <span className="mt-2 leading-relaxed text-pretty text-mk-muted">{feature.summary}</span>
        <span className="mk-module__more">
          {more}
          <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />
        </span>
      </Link>
    </Spotlight>
  );
}
