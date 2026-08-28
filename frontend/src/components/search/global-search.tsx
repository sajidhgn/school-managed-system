"use client";

import {
  AlertTriangle,
  ArrowRight,
  CornerDownLeft,
  GraduationCap,
  Layers,
  Mail,
  Receipt,
  School,
  ScrollText,
  Search,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import * as React from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { AnyStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useRecentSearches, useSearch, useSearchConfig } from "@/hooks/use-search";
import { activeType, withFilter } from "@/lib/api/resources/search";
import type { SearchEntity, SearchHit, SearchResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The global search omnibar.
 *
 * =============================================================================
 * THE BOX IS THE SAME FOR EVERYONE; WHAT IT SEARCHES IS NOT
 * =============================================================================
 *   There is no permission logic in this file, and there must not be. Which entity
 *   kinds appear as scope chips, which filters those scopes accept, which example
 *   queries are worth suggesting — all of it arrives from `GET /search/config`,
 *   derived server-side from the caller's own permissions and role.
 *
 *   So a teacher's box offers Students, Sections and Classes; an accountant's leads
 *   with Fee vouchers; a principal's includes Campuses and Roles. The component
 *   renders whatever it is told, which means a permission change in the roles screen
 *   reshapes this box with no frontend release — and, more importantly, that this
 *   file can never disagree with the server about who may see what.
 *
 * ONE SOURCE OF TRUTH FOR THE QUERY
 *   Scope chips write `type:` into the same string the user types, rather than
 *   living in separate state. A query built by clicking is therefore a query that
 *   can be edited by typing, shared with a colleague, and pasted back in. Two
 *   parallel representations of "what am I searching for" would drift within a week.
 *
 * KEYBOARD FIRST
 *   This is a power-user surface: ⌘K to open, arrows to move, Enter to go, Escape
 *   to leave. It is implemented as a real combobox — the input keeps focus at all
 *   times and `aria-activedescendant` moves the selection — so screen readers
 *   announce the highlighted result instead of losing the user in a list they
 *   cannot reach.
 */

/** Icons the server can name, resolved explicitly so the bundler can tree-shake. */
const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  GraduationCap,
  Users,
  Receipt,
  Layers,
  School,
  Mail,
  ScrollText,
  ShieldCheck,
  Search,
};

function Icon({ name, className }: { name: string; className?: string }) {
  const Resolved = ICONS[name] ?? Search;
  return <Resolved className={className} />;
}

export function GlobalSearch() {
  const { t } = useTranslations();
  const router = useRouter();

  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);

  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  // Fetched on MOUNT, not on open. It is one small request per session (cached
  // forever after), and it is what the empty state is made of — scope chips and
  // example queries. Deferring it to the first ⌘K means the first thing a new user
  // sees is an empty panel that fills in a moment later, which is precisely the
  // moment they most need to be told what the box can do.
  const { data: config } = useSearchConfig();
  const { data, isSearching, enabled } = useSearch(query);
  const { recent, remember, clear } = useRecentSearches();

  // One flat list behind the grouped display: arrow keys move through results in
  // reading order, ignoring the group headings they pass under.
  const flat = React.useMemo(() => flatten(data), [data]);

  // Stamp rows with their campus only when the results ACTUALLY span more than
  // one. `cross_school` merely says the search was allowed to span campuses — a
  // principal who has not opened a branch searches org-wide even in a single-campus
  // organization, and labelling every row with the only campus there is is noise.
  const showSchool = React.useMemo(
    () => new Set(flat.map((hit) => hit.school_name).filter(Boolean)).size > 1,
    [flat],
  );

  React.useEffect(() => setActiveIndex(0), [data]);

  // ⌘K / Ctrl+K from anywhere in the app.
  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((previous) => !previous);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const go = React.useCallback(
    (hit: SearchHit) => {
      remember(query);
      setOpen(false);
      // `Route` is a build-time-checked type and these URLs are built from a
      // server-side template, so the cast is where the two systems meet. The
      // templates live in `modules/search/providers.py` and point at real pages.
      router.push(hit.url as Route);
    },
    [query, remember, router],
  );

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!flat.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      // Wraps at both ends: reaching the bottom and pressing down again should
      // return to the first result, not sit there doing nothing.
      setActiveIndex((current) => (current + step + flat.length) % flat.length);
      return;
    }
    if (event.key === "Enter" && flat[activeIndex]) {
      event.preventDefault();
      go(flat[activeIndex]);
    }
  }

  // Keep the highlighted row in view while arrow-keying past the fold.
  React.useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const pinnedType = activeType(query);
  const groups = data?.groups ?? [];
  const showEmptyState = !enabled;
  const noResults = enabled && !isSearching && groups.length === 0;

  return (
    <>
      <SearchTrigger label={t.search.open} placeholder={t.search.placeholder} onClick={() => setOpen(true)} />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          // Top-anchored rather than centred: the list grows downward, and a
          // vertically-centred palette jumps as results arrive.
          className="top-[12svh] max-w-2xl translate-y-0 gap-0 overflow-hidden p-0 [&>button]:hidden"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            inputRef.current?.focus();
          }}
          aria-label={t.search.title}
        >
          {/* --- Input ---------------------------------------------------- */}
          <div className="flex items-center gap-3 border-b border-border px-4">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder={t.search.placeholder}
              maxLength={config?.max_query_length ?? 200}
              className="h-14 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              // The combobox contract: focus never leaves the input, and the
              // highlighted option is announced through `aria-activedescendant`.
              role="combobox"
              aria-expanded={flat.length > 0}
              aria-controls="global-search-results"
              aria-activedescendant={flat.length ? `search-hit-${activeIndex}` : undefined}
              aria-autocomplete="list"
              autoComplete="off"
              spellCheck={false}
            />
            {query ? (
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                onClick={() => {
                  setQuery("");
                  inputRef.current?.focus();
                }}
              >
                <X className="size-3.5" aria-hidden />
                <span className="sr-only">{t.search.clear}</span>
              </Button>
            ) : null}
            <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
              ESC
            </kbd>
          </div>

          {/* --- Scope chips ---------------------------------------------- */}
          {config?.scopes.length ? (
            <div className="flex gap-1.5 overflow-x-auto border-b border-border px-3 py-2">
              <ScopeChip
                label={t.search.allScopes}
                active={pinnedType === null}
                onClick={() => setQuery((current) => withFilter(current, "type", null))}
              />
              {config.scopes.map((scope) => (
                <ScopeChip
                  key={scope.type}
                  label={scope.label}
                  icon={scope.icon}
                  active={pinnedType === scope.type}
                  onClick={() =>
                    setQuery((current) =>
                      withFilter(current, "type", pinnedType === scope.type ? null : scope.type),
                    )
                  }
                />
              ))}
            </div>
          ) : null}

          {/* --- Body ------------------------------------------------------ */}
          <div ref={listRef} id="global-search-results" role="listbox" aria-label={t.search.title} className="max-h-[52svh] overflow-y-auto">
            {showEmptyState ? (
              <EmptyState
                examples={config?.examples ?? []}
                recent={recent}
                onPick={(value) => {
                  setQuery(value);
                  inputRef.current?.focus();
                }}
                onClearRecent={clear}
              />
            ) : null}

            {noResults ? (
              <p className="px-4 py-10 text-center text-sm text-muted-foreground">
                {t.search.noResults}
              </p>
            ) : null}

            {groups.map((group) => (
              <section key={group.type} className="py-1">
                <div className="flex items-center justify-between px-4 py-1.5">
                  <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </h3>
                  {group.truncated ? (
                    <button
                      type="button"
                      className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                      onClick={() =>
                        setQuery((current) => withFilter(current, "type", group.type))
                      }
                    >
                      {t.search.seeAll.replace("{count}", String(group.total))}
                    </button>
                  ) : null}
                </div>

                {group.hits.map((hit) => {
                  const index = flat.indexOf(hit);
                  return (
                    <ResultRow
                      key={`${hit.type}-${hit.id}`}
                      hit={hit}
                      icon={group.icon}
                      index={index}
                      active={index === activeIndex}
                      showSchool={showSchool}
                      matchedElsewhere={t.search.matchedElsewhere}
                      onSelect={() => go(hit)}
                      onHover={() => setActiveIndex(index)}
                    />
                  );
                })}
              </section>
            ))}
          </div>

          {/* --- Footer: how the query was read, and what went wrong ------- */}
          <Footer response={data} isSearching={isSearching} />
        </DialogContent>
      </Dialog>
    </>
  );
}

/** The header button. Shows the shortcut, because nobody discovers ⌘K by accident. */
function SearchTrigger({
  label,
  placeholder,
  onClick,
}: {
  label: string;
  placeholder: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md border border-input bg-card px-3 text-sm text-muted-foreground shadow-sm transition-colors",
        "hover:border-ring hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        // Icon-only below `sm`, where a full search field would crowd out the
        // campus name the header exists to show.
        "w-9 justify-center sm:w-64 sm:justify-start",
      )}
      aria-label={label}
    >
      <Search className="size-4 shrink-0" aria-hidden />
      <span className="hidden truncate sm:inline">{placeholder}</span>
      <kbd className="ms-auto hidden rounded border border-border px-1.5 py-0.5 text-[10px] sm:inline">
        ⌘K
      </kbd>
    </button>
  );
}

function ScopeChip({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:border-ring hover:text-foreground",
      )}
    >
      {icon ? <Icon name={icon} className="size-3" /> : null}
      {label}
    </button>
  );
}

function ResultRow({
  hit,
  icon,
  index,
  active,
  showSchool,
  matchedElsewhere,
  onSelect,
  onHover,
}: {
  hit: SearchHit;
  icon: string;
  index: number;
  active: boolean;
  showSchool: boolean;
  matchedElsewhere: string;
  onSelect: () => void;
  onHover: () => void;
}) {
  return (
    <div
      id={`search-hit-${index}`}
      data-index={index}
      role="option"
      aria-selected={active}
      tabIndex={-1}
      onClick={onSelect}
      onMouseMove={onHover}
      className={cn(
        "flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm",
        active && "bg-accent",
      )}
    >
      <Icon name={icon} className="size-4 shrink-0 text-muted-foreground" />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{hit.title}</span>
          {hit.status ? <AnyStatusBadge status={hit.status} /> : null}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {hit.subtitle ? <span className="truncate">{hit.subtitle}</span> : null}
          {hit.subtitle && hit.context ? <span aria-hidden>·</span> : null}
          {hit.context ? <span className="truncate">{hit.context}</span> : null}
          {/* The row matched on a field this card does not show — a guardian's
              phone number, a voucher's notes. Saying so turns a baffling result
              into an explained one. */}
          {hit.matched_on === null ? (
            <span className="shrink-0 italic opacity-70">{matchedElsewhere}</span>
          ) : null}
        </div>
      </div>

      {/* Only when the results actually span campuses. Stamping every row with the
          campus name in a single-campus search is noise. */}
      {showSchool && hit.school_name ? (
        <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
          {hit.school_name}
        </span>
      ) : null}

      <ArrowRight
        className={cn("size-3.5 shrink-0 text-muted-foreground", active ? "opacity-100" : "opacity-0")}
        aria-hidden
      />
    </div>
  );
}

function EmptyState({
  examples,
  recent,
  onPick,
  onClearRecent,
}: {
  examples: string[];
  recent: string[];
  onPick: (value: string) => void;
  onClearRecent: () => void;
}) {
  const { t } = useTranslations();

  return (
    <div className="px-4 py-4">
      {recent.length ? (
        <section className="mb-4">
          <div className="mb-1.5 flex items-center justify-between">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t.search.recent}
            </h3>
            <button
              type="button"
              onClick={onClearRecent}
              className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              {t.search.clearRecent}
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {recent.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => onPick(item)}
                className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-ring hover:text-foreground"
              >
                {item}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {/* An empty box is the only moment anyone reads documentation for a query
          language, so this is where it goes — and the examples are the ones the
          server picked for THIS role, not a fixed list. */}
      {examples.length ? (
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.search.tryThis}
          </h3>
          <ul className="space-y-1">
            {examples.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  onClick={() => onPick(example)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start text-sm hover:bg-accent"
                >
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{example}</code>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="mt-4 text-xs text-muted-foreground">{t.search.syntaxHint}</p>
    </div>
  );
}

function Footer({ response, isSearching }: { response?: SearchResponse; isSearching: boolean }) {
  const { t } = useTranslations();
  const summary = response?.parsed.summary ?? [];
  const warnings = response?.warnings ?? [];

  return (
    <div className="border-t border-border bg-muted/40 px-4 py-2">
      {/* Warnings first: an ignored filter changes what the results MEAN, and
          burying it under a row count is how a user concludes the box is broken. */}
      {warnings.length ? (
        <ul className="mb-1.5 space-y-1" role="status">
          {warnings.map((warning) => (
            <li
              key={warning}
              // Tinted, following the `warning` badge variant: `--warning-foreground`
              // is a deep amber meant to sit ON an amber wash, and on the plain
              // footer it reads as ordinary near-black text — a warning nobody
              // notices is not a warning. `dark:text-warning` for the same reason
              // the badge does it: the deep tone disappears against a dark surface.
              className="flex items-start gap-1.5 rounded-md bg-warning/15 px-2 py-1 text-xs text-warning-foreground dark:text-warning"
            >
              <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {/* How the server read the query, in words. This is what makes an advanced
            syntax learnable: you can see that `status:pending` was understood as a
            filter rather than as text. */}
        {summary.length ? <span className="truncate">{summary.join(" · ")}</span> : null}

        <span className="ms-auto flex items-center gap-3">
          {isSearching ? (
            <span>{t.search.searching}</span>
          ) : response ? (
            <span aria-live="polite">
              {t.search.resultCount.replace("{count}", String(response.total))}
              {response.cross_school ? ` · ${t.search.allCampuses}` : ""}
            </span>
          ) : null}
          <span className="hidden items-center gap-1 sm:flex">
            <kbd className="rounded border border-border px-1 py-0.5 text-[10px]">↑↓</kbd>
            <CornerDownLeft className="size-3" aria-hidden />
          </span>
        </span>
      </div>
    </div>
  );
}

/** Grouped results as one ordered list, for arrow-key navigation. */
function flatten(response: SearchResponse | undefined): SearchHit[] {
  return response?.groups.flatMap((group) => group.hits) ?? [];
}

export type { SearchEntity };
