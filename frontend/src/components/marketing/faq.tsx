"use client";

import { Accordion } from "@heroui/react";

import type { Pair } from "@/components/marketing/copy";

/**
 * A page's questions as a HeroUI accordion; each question is an <h3>.
 *
 * A client module because `@heroui/react` can only be imported from one, and a
 * server component cannot reach `Accordion.Item` through a client boundary.
 */
export function Faq({ items }: { items: readonly Pair[] }) {
  return (
    <Accordion className="border-t border-mk-line">
      {items.map(([question, answer]) => (
        <Accordion.Item key={question}>
          <Accordion.Heading>
            <Accordion.Trigger className="py-5 text-start text-[1.05rem] font-semibold">
              {question}
              <Accordion.Indicator />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel>
            <Accordion.Body className="max-w-[68ch] pb-6 leading-relaxed text-mk-muted">{answer}</Accordion.Body>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
