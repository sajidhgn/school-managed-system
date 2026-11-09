import * as React from "react";

/**
 * Fill `{name}` placeholders in a catalog string.
 *
 * Catalog strings stay plain strings (see `messages.ts`) so a missing translation is
 * a type error. Values are substituted here rather than concatenated at the call
 * site, because word order differs between English and Urdu: "3 of 10 paid" is
 * "10 میں سے 3 ادا", and only a template can carry that.
 *
 * An unknown placeholder is left as written, so a typo shows up on screen instead of
 * silently rendering an empty string.
 */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}

/**
 * `fill()` for a template whose placeholders are elements — a link, a bold amount,
 * a phone number that must stay left-to-right — so the sentence around them is
 * still ONE translated string and keeps its own word order. Gluing translated
 * halves around the element would fix the English order into every language.
 *
 * An unknown placeholder is left as written, like `fill()`.
 */
export function fillNodes(
  template: string,
  values: Record<string, React.ReactNode>,
): React.ReactNode[] {
  return template
    .split(/(\{\w+\})/g)
    .filter(Boolean)
    .map((part, index) => {
      const key = /^\{(\w+)\}$/.exec(part)?.[1];
      return key !== undefined && key in values
        ? React.createElement(React.Fragment, { key: index }, values[key])
        : part;
    });
}

/**
 * Keep a code or number reading left-to-right inside a translated sentence:
 * "2026-001", "FV-2026-00004", "0300 1234567". In an Urdu sentence the bidi
 * algorithm otherwise splits such runs at the hyphen or space and swaps the halves
 * ("001-2026"). Wraps the text in an invisible LTR isolate.
 *
 * DISPLAY ONLY — never use it on a value that is saved or sent to the API.
 */
export function ltr(text: string | number): string {
  return `\u2066${text}\u2069`;
}
