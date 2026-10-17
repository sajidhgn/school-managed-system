import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * WhatsApp's inline markup: `*bold*`, `_italic_`, `~strike~`. The marker must hug
 * non-space text on both sides, as in the app ("2 * 3 * 4" stays literal).
 */
const MARKUP = /([*_~])(?=\S)([^\n]*?\S)\1/g;

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKUP)) {
    const [whole, marker, inner] = match;
    const start = match.index;
    if (start > last) nodes.push(text.slice(last, start));
    const key = `${keyPrefix}-${start}`;
    if (marker === "*") nodes.push(<strong key={key}>{inner}</strong>);
    else if (marker === "_") nodes.push(<em key={key}>{inner}</em>);
    else nodes.push(<s key={key}>{inner}</s>);
    last = start + whole.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/**
 * A message as WhatsApp shows it. Built from React text nodes — never HTML — so a
 * diary the agent read off a photo cannot inject markup.
 */
export function WhatsAppText({ text, className }: { text: string; className?: string }) {
  const lines = text.split("\n");
  return (
    <div className={cn("whitespace-pre-wrap break-words text-sm leading-relaxed", className)}>
      {lines.map((line, index) => (
        <React.Fragment key={index}>
          {renderInline(line, String(index))}
          {index < lines.length - 1 && "\n"}
        </React.Fragment>
      ))}
    </div>
  );
}

/** An outgoing chat bubble on WhatsApp's wallpaper colours, light and dark. */
export function WhatsAppBubble({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("rounded-lg bg-[#efeae2] p-3 dark:bg-[#0b141a]", className)}>
      <div className="ms-auto w-fit max-w-full rounded-lg rounded-tr-none bg-[#d9fdd3] px-3 py-2 text-[#111b21] shadow-sm dark:bg-[#005c4b] dark:text-[#e9edef]">
        <WhatsAppText text={text} />
      </div>
    </div>
  );
}
