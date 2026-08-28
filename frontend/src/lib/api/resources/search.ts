import { api } from "@/lib/api/client";
import type {
  SearchConfigResponse,
  SearchEntity,
  SearchResponse,
  SearchSuggestion,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/search/router.py. */

export interface SearchParams {
  q?: string | null;
  /** Results per entity type. The backend caps this at 25. */
  limit?: number | null;
}

export const searchApi = {
  search: (params: SearchParams = {}, signal?: AbortSignal) =>
    api.get<SearchResponse>("/search", { params: { ...params }, signal }),

  suggest: (params: SearchParams = {}, signal?: AbortSignal) =>
    api.get<SearchSuggestion[]>("/search/suggest", { params: { ...params }, signal }),

  /**
   * What this member's search box can do.
   *
   * Scopes, filters and examples are all derived server-side from the caller's
   * permissions and role — so the omnibar never needs its own copy of the
   * permission catalog, and a role edit changes the box on the next load.
   */
  config: () => api.get<SearchConfigResponse>("/search/config"),
};

/**
 * Add or replace a `key:value` filter in a raw query string.
 *
 * The scope chips in the omnibar write `type:` into the same text the user is
 * typing, rather than living in separate component state. One source of truth
 * means a query built by clicking is a query that can be edited by typing — and
 * copied, shared, and bookmarked.
 */
export function withFilter(query: string, key: string, value: string | null): string {
  const stripped = query
    .replace(new RegExp(`(^|\\s)-?${key}:(?:"[^"]*"|[^\\s]+)`, "gi"), " ")
    .replace(/\s+/g, " ")
    .trim();

  if (value === null) return stripped;
  const quoted = /\s/.test(value) ? `"${value}"` : value;
  return stripped ? `${key}:${quoted} ${stripped}` : `${key}:${quoted}`;
}

/** The `type:` value currently pinned in a query, if exactly one is. */
export function activeType(query: string): SearchEntity | null {
  const matches = [...query.matchAll(/(^|\s)type:("([^"]*)"|[^\s]+)/gi)].map(
    (match) => (match[3] ?? match[2] ?? "").toLowerCase(),
  );
  return matches.length === 1 ? (matches[0] as SearchEntity) : null;
}
