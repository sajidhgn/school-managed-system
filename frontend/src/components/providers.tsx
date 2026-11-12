"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { ThemeProvider } from "next-themes";

import { Toaster } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";

/**
 * App-wide providers.
 *
 * The QueryClient is created inside state so each browser session gets exactly
 * one, and — importantly on the server — no cache is shared between requests
 * from different users.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Never retry what won't succeed: auth, permissions, validation,
              // missing records. Only transient/server faults are worth a retry.
              if (error instanceof ApiError) {
                if (error.status === 401 || error.status === 403) return false;
                if (error.status === 404 || error.status === 422) return false;
              }
              return failureCount < 2;
            },
          },
          // `always`: a write attempted offline fails at once with an
          // `OfflineError` ("No connection") instead of pausing with its button
          // spinning until the connection returns. Writes that CAN wait — offline
          // attendance — are queued explicitly (`lib/offline`); everything else
          // must tell the user it needs a connection.
          mutations: { retry: false, networkMode: "always" },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        {children}
        <Toaster />
      </ThemeProvider>
      {process.env.NODE_ENV === "development" ? (
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      ) : null}
    </QueryClientProvider>
  );
}
