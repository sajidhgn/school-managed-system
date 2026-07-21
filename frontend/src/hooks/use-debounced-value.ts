"use client";

import * as React from "react";

/**
 * Delay a rapidly-changing value.
 *
 * Used for the search box so typing "Fatima" issues one request instead of six.
 */
export function useDebouncedValue<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = React.useState(value);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
