import * as React from "react";

/**
 * Render the small Markdown subset an AI answer uses — paragraphs, bullet and
 * numbered lists, headings, **bold**, *italic* and `code` — as React elements.
 *
 * WHY NOT A LIBRARY OR innerHTML: the text comes from a model that was fed book
 * pages, and book pages are uploaded by users. Building elements (never HTML
 * strings) means nothing in that text can become a tag or a script. The subset is
 * all an answer needs, and it costs no dependency.
 *
 * `renderToken` lets the caller turn extra inline syntax into components — the
 * library answer uses it for `[1]`-style citations.
 */
export function SimpleMarkdown({
  text,
  renderCitation,
  className,
}: {
  text: string;
  /** Called for each `[n]`; return null to print it as plain text. */
  renderCitation?: (n: number, key: string) => React.ReactNode;
  className?: string;
}) {
  const blocks = parseBlocks(text);
  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const key = `b${index}`;
        if (block.kind === "heading") {
          return (
            <p key={key} className="mt-3 font-semibold first:mt-0">
              {inline(block.text, key, renderCitation)}
            </p>
          );
        }
        if (block.kind !== "p") {
          const List = block.kind === "ul" ? "ul" : "ol";
          return (
            <List
              key={key}
              className={`mt-2 space-y-1 ps-5 first:mt-0 ${block.kind === "ul" ? "list-disc" : "list-decimal"}`}
            >
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{inline(item, `${key}-${itemIndex}`, renderCitation)}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={key} className="mt-2 first:mt-0">
            {inline(block.text, key, renderCitation)}
          </p>
        );
      })}
    </div>
  );
}

type Block =
  | { kind: "p"; text: string }
  | { kind: "heading"; text: string }
  | { kind: "ul" | "ol"; items: string[] };

function parseBlocks(text: string): Block[] {
  type ListBlock = { kind: "ul" | "ol"; items: string[] };
  const blocks: Block[] = [];
  // A holder object rather than a `let`: TypeScript does not track assignments made
  // inside the flush closures, and would otherwise narrow `list` to `null` for good.
  const open: { paragraph: string[]; list: ListBlock | null } = { paragraph: [], list: null };

  const flushParagraph = () => {
    if (open.paragraph.length) blocks.push({ kind: "p", text: open.paragraph.join(" ") });
    open.paragraph = [];
  };
  const flushList = () => {
    if (open.list) blocks.push(open.list);
    open.list = null;
  };

  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    const item = /^[-*•]\s+(.*)$/.exec(line) ?? /^\d+[.)]\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: "heading", text: heading[1] });
    } else if (item) {
      flushParagraph();
      const kind = /^\d/.test(line) ? "ol" : "ul";
      if (open.list?.kind !== kind) {
        flushList();
        open.list = { kind, items: [] };
      }
      open.list!.items.push(item[1]);
    } else {
      flushList();
      open.paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

/** **bold**, *italic* / _italic_, `code`, and [n] citations. */
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[\d+\](?:\s*\[\d+\])*)/g;

function inline(
  text: string,
  key: string,
  renderCitation?: (n: number, key: string) => React.ReactNode,
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const k = `${key}-i${index++}`;
    if (token.startsWith("**")) {
      out.push(<strong key={k}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(
        <code key={k} className="rounded bg-muted px-1 py-0.5 text-[0.9em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("[")) {
      const numbers = [...token.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1]));
      for (const [i, n] of numbers.entries()) {
        out.push(renderCitation ? renderCitation(n, `${k}-${i}`) : `[${n}]`);
      }
    } else {
      out.push(<em key={k}>{token.slice(1, -1)}</em>);
    }
    last = at + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
