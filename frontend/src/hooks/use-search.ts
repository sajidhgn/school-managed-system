"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { queryKeys } from "@/lib/api/query-keys";
import { searchApi } from "@/lib/api/resources/search";

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 250;

/**
 * Whether a query is worth sending.
 *
 * Two characters, UNLESS the user has typed a filter — `type:student` is a
 * complete, meaningful query on its own (show me the student directory) and
 * refusing to run it until they add a search term would make the filter chips
 * feel broken.
 */
export function isSearchable(query: string): boolean {
  const trimmed = query.trim();
  return trimmed.length >= MIN_QUERY_LENGTH || /[a-z_]+:/i.test(trimmed);
}

/**
 * Grouped results for the omnibar.
 *
 * Debounced, so typing "Fatima" is one request rather than six. `placeholderData`
 * keeps the previous results on screen while the next request is in flight — a
 * list that empties and refills on every keystroke is unreadable, and it moves the
 * row under the user's cursor just as they go to click it.
 */
export function useSearch(query: string, { limit = 5 }: { limit?: number } = {}) {
  const debounced = useDebouncedValue(query.trim(), DEBOUNCE_MS);
  const enabled = isSearchable(debounced);

  const result = useQuery({
    queryKey: queryKeys.search.results(debounced, limit),
    queryFn: ({ signal }) => searchApi.search({ q: debounced, limit }, signal),
    enabled,
    placeholderData: (previous) => previous,
    // Results go stale the moment anyone edits a student, but the omnibar is
    // short-lived and re-queried on every open. Ten seconds is long enough to
    // make arrow-keying back and forth free, short enough that a search run after
    // an edit reflects it.
    staleTime: 10_000,
  });

  return {
    ...result,
    /** True only while waiting on a query the user has actually finished typing. */
    isSearching: enabled && (result.isFetching || query.trim() !== debounced),
    enabled,
  };
}

/**
 * The caller's own search capabilities: which scopes, filters and examples.
 *
 * Fetched once and held for the session. It changes only when the caller's role
 * permissions change, which invalidates their token anyway.
 */
export function useSearchConfig(enabled = true) {
  return useQuery({
    queryKey: queryKeys.search.config,
    queryFn: () => searchApi.config(),
    enabled,
    staleTime: Infinity,
  });
}

/**
 * Recent searches, per browser.
 *
 * DELIBERATELY NOT SERVER-SIDE. A row per keystroke per user is a surprising
 * amount of write traffic, and the list of names a staff member looked up is
 * personal data with no operational use. It belongs to the person who typed it,
 * on the device they typed it on.
 */
const RECENT_KEY = "educloud.search.recent";
const RECENT_LIMIT = 6;

export function useRecentSearches() {
  const [recent, setRecent] = React.useState<string[]>([]);

  React.useEffect(() => {
    // Read in an effect, not in the initial state: `localStorage` does not exist
    // during the server render, and reading it in `useState` would make the first
    // client render disagree with the server's and throw a hydration error.
    try {
      const stored = window.localStorage.getItem(RECENT_KEY);
      if (stored) setRecent(JSON.parse(stored) as string[]);
    } catch {
      // Private mode, disabled storage, corrupted JSON — recents are a
      // convenience, never a reason to break the search box.
    }
  }, []);

  const remember = React.useCallback((query: string) => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setRecent((previous) => {
      const next = [trimmed, ...previous.filter((item) => item !== trimmed)].slice(0, RECENT_LIMIT);
      try {
        window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // As above.
      }
      return next;
    });
  }, []);

  const clear = React.useCallback(() => {
    setRecent([]);
    try {
      window.localStorage.removeItem(RECENT_KEY);
    } catch {
      // As above.
    }
  }, []);

  return { recent, remember, clear };
}
