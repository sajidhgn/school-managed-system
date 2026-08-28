"""The search query language -- parsing what the user typed into something SQL can use.

WHY THIS FILE EXISTS
    A single text box has to serve two very different users. A teacher types
    `ahmed` and wants their students. A registrar types
    `type:student status:pending class:"Grade 10" -transferred` and wants an exact
    slice of the admissions queue. Both are the same box, and the difference between
    them is entirely in how the string is read.

    Putting that reading in one place means the operators are defined once, tested
    once, and behave identically in the omnibar, the suggest endpoint and any future
    saved-search feature. Scattering `if ":" in q` across providers is how a search
    syntax ends up meaning three different things in three different places.

RESPONSIBILITY
    Lexing and interpretation only. This module knows the *shape* of a query
    (`key:value`, `"phrase"`, `-negation`) and nothing about students, permissions,
    or SQL. It cannot reject a filter for being unauthorised, because it does not
    know who is asking -- that is `service.py`'s job.

THE GRAMMAR
    term            bare word, matched as a substring, case-insensitive
    "two words"     phrase, matched as a unit rather than as two terms
    -term           exclusion; a row matching it is dropped even if it matches others
    key:value       filter; `type:`, `status:`, `class:`, `school:`, `after:` ...
    -key:value      negated filter, e.g. `-status:paid`
    key:"a value"   quoted filter value, for names with spaces

WHY UNKNOWN KEYS BECOME PLAIN TEXT INSTEAD OF ERRORS
    Someone searching for a student whose guardian email is `billing:ahmed@x.com`
    should get that student, not a 400. An unknown key is therefore searched
    literally and a warning is attached to the response so the UI can say "`foo:` is
    not a filter -- searched as text" without ever blocking the search.

    The inverse -- erroring on anything unrecognised -- looks rigorous and is
    actively hostile in a box people type into fifty times a day.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

# --- Limits ----------------------------------------------------------------
#
# A search box is an unauthenticated-shaped surface even behind a login: it accepts
# arbitrary text and turns it into SQL predicates. Every one of these caps exists so
# that the *cost* of a query stays bounded no matter what is typed.

MAX_QUERY_LENGTH = 200
"""Matches the `q` parameter's own `max_length`; enforced again here because the
parser is also reachable from the CLI and from tests."""

MAX_TERMS = 6
"""Each term multiplies the number of CASE branches in the ranking expression.
Six is generous for a human and cheap for Postgres; the rest are dropped with a
warning rather than silently ignored."""

MAX_FILTER_VALUES = 8
"""`status:active status:pending status:...` becomes an IN list. Capped so a pasted
wall of text cannot build an unbounded one."""

MIN_TERM_LENGTH = 1
"""Single characters are allowed deliberately: section names are literally "A"."""


# ---------------------------------------------------------------------------
# Filter keys
# ---------------------------------------------------------------------------

TYPE_KEY = "type"
"""Restricts which entity kinds are searched. Special-cased everywhere because it
selects the *providers* rather than filtering rows within one."""

FILTER_KEYS: frozenset[str] = frozenset(
    {
        TYPE_KEY,
        "status",  # enrollment status, voucher status, membership status...
        "school",  # campus id, code or name -- narrows, never widens (see service)
        "class",  # class name or level, e.g. class:"Grade 10" or class:10
        "section",  # section name, e.g. section:A
        "role",  # role name or code, for members and invitations
        "year",  # academic year, e.g. year:2026-2027
        "after",  # created on or after an ISO date
        "before",  # created on or before an ISO date
    }
)

ALL_SCOPE = "all"
"""`school:all` -- an organization-level caller asking to search every campus at
once, rather than the one currently open in the UI. See `service.resolve_scope`."""


# ---------------------------------------------------------------------------
# The token scanner
# ---------------------------------------------------------------------------

# One regex, scanned left to right. The alternation order matters: a quoted value
# must be tried before the bare-word branch, or `key:"a b"` would lex as `key:"a`
# followed by a stray `b"`.
_TOKEN_RE = re.compile(
    r"""
    (?P<neg>-)?                       # optional leading minus  -> exclusion
    (?:(?P<key>[A-Za-z_][A-Za-z0-9_]*):)?   # optional  key:
    (?:
        "(?P<quoted>[^"]*)"           # "a quoted phrase"
      | (?P<bare>[^\s"]+)             # or a bare run of non-space
    )
    """,
    re.VERBOSE,
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """The user's string, decomposed. Immutable: parsing happens exactly once.

    Frozen because this object is handed to every provider in turn, and a provider
    that could mutate it would silently change what the next provider searches for.
    """

    raw: str

    terms: tuple[str, ...] = ()
    """Bare words. Each must match SOMEWHERE in a row for that row to qualify."""

    phrases: tuple[str, ...] = ()
    """Quoted runs, matched as a unit. `"grade 10"` must not match a row that
    happens to contain "grade" in one column and "10" in another."""

    exclusions: tuple[str, ...] = ()
    """Text that disqualifies a row outright. AND NOT, applied across every
    searchable column of the provider."""

    filters: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """key -> values. Multiple values of one key are OR'd (`status:active
    status:pending` means either), different keys are AND'd."""

    negated_filters: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """key -> values the row must NOT have. `-status:paid` on vouchers is the
    single most useful query in the fees module."""

    warnings: tuple[str, ...] = ()
    """Human-readable notes about what was ignored or reinterpreted. Surfaced in the
    response so the UI can explain itself; never an error."""

    # -- derived ------------------------------------------------------------

    @property
    def needles(self) -> tuple[str, ...]:
        """Everything that must match, in one list.

        Phrases come first so that the most selective predicate is evaluated first
        in the generated AND chain -- Postgres is free to reorder, but the plan is
        easier to read when the expression already reflects intent.
        """
        return (*self.phrases, *self.terms)

    @property
    def has_text(self) -> bool:
        return bool(self.needles)

    @property
    def is_empty(self) -> bool:
        """Nothing to search AND nothing to filter by -- there is no query here."""
        return not self.needles and not self.filters and not self.negated_filters

    @property
    def requested_types(self) -> tuple[str, ...]:
        """Values of `type:`, lowercased. Empty means "every type I'm allowed"."""
        return self.filters.get(TYPE_KEY, ())

    @property
    def excluded_types(self) -> tuple[str, ...]:
        """Values of `-type:`. Lets `-type:audit` quieten a noisy provider."""
        return self.negated_filters.get(TYPE_KEY, ())

    def filter_values(self, key: str) -> tuple[str, ...]:
        return self.filters.get(key, ())

    def first(self, key: str) -> str | None:
        """The first value for a single-valued filter such as `year:`."""
        values = self.filters.get(key)
        return values[0] if values else None

    def date_bound(self, key: str) -> date | None:
        """`after:`/`before:` as a date, or None if absent or unparseable.

        Unparseable dates are dropped during parsing with a warning rather than
        surfaced here, so this never raises mid-query-build.
        """
        value = self.first(key)
        if value is None or not _ISO_DATE_RE.match(value):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:  # e.g. 2026-13-45
            return None


def parse(raw: str | None) -> ParsedQuery:
    """Turn a raw search string into a `ParsedQuery`. Never raises.

    Every malformed input has a defined, useful reading:

      * over-long input is truncated, not rejected
      * an unknown `key:` is searched as literal text
      * an unclosed quote is treated as a bare word (the closing quote a user has
        not typed *yet* is the normal state of a box being typed into)
      * a bad date is dropped from the filter and mentioned in `warnings`

    That last point is the whole design principle: this runs on every keystroke of a
    debounced omnibar, so "not finished typing" must never look like "wrong".
    """
    warnings: list[str] = []
    text = (raw or "").strip()

    if not text:
        return ParsedQuery(raw="")

    if len(text) > MAX_QUERY_LENGTH:
        text = text[:MAX_QUERY_LENGTH]
        warnings.append(f"Query truncated to {MAX_QUERY_LENGTH} characters.")

    terms: list[str] = []
    phrases: list[str] = []
    exclusions: list[str] = []
    filters: dict[str, list[str]] = {}
    negated: dict[str, list[str]] = {}
    unknown_keys: set[str] = set()

    for match in _TOKEN_RE.finditer(text):
        negative = match.group("neg") is not None
        key = match.group("key")
        quoted = match.group("quoted")
        value = (quoted if quoted is not None else match.group("bare") or "").strip()

        if not value:
            # `key:` with nothing after it -- someone mid-type. Silently skipped so
            # the omnibar does not flash a warning between two keystrokes.
            continue

        if key is not None:
            normalised = key.lower()
            if normalised in FILTER_KEYS:
                bucket = negated if negative else filters
                values = bucket.setdefault(normalised, [])
                lowered = value.lower()
                if lowered not in values:
                    if len(values) < MAX_FILTER_VALUES:
                        values.append(lowered)
                    else:
                        warnings.append(
                            f"Only the first {MAX_FILTER_VALUES} `{normalised}:` values were used."
                        )
                continue
            # Unknown key: fall through and search `key:value` as literal text.
            unknown_keys.add(normalised)
            value = f"{key}:{value}"

        if len(value) < MIN_TERM_LENGTH:
            continue

        if negative:
            if value not in exclusions:
                exclusions.append(value)
        elif quoted is not None and " " in value:
            # Only a MULTI-WORD quoted run is a phrase. `"ahmed"` is just a term,
            # and treating it as a phrase would needlessly change its ranking.
            if value not in phrases:
                phrases.append(value)
        elif value not in terms:
            terms.append(value)

    if unknown_keys:
        warnings.append(
            "Not a filter, searched as text: "
            + ", ".join(f"`{k}:`" for k in sorted(unknown_keys))
            + ". Available filters: "
            + ", ".join(f"`{k}:`" for k in sorted(FILTER_KEYS))
            + "."
        )

    total_needles = len(terms) + len(phrases)
    if total_needles > MAX_TERMS:
        # Drop bare terms first: a phrase is a stronger, more deliberate signal of
        # what the user actually meant than the fifth loose word.
        keep = max(0, MAX_TERMS - len(phrases))
        terms = terms[:keep]
        phrases = phrases[:MAX_TERMS]
        warnings.append(f"Only the first {MAX_TERMS} search terms were used.")

    warnings.extend(_date_warnings(filters))

    return ParsedQuery(
        raw=text,
        terms=tuple(terms),
        phrases=tuple(phrases),
        exclusions=tuple(exclusions),
        filters={k: tuple(v) for k, v in filters.items()},
        negated_filters={k: tuple(v) for k, v in negated.items()},
        warnings=tuple(warnings),
    )


def _date_warnings(filters: dict[str, list[str]]) -> list[str]:
    """Drop unparseable `after:`/`before:` values in place, reporting each one.

    Mutates `filters` deliberately: a bad date must not reach the query builder,
    where it would either raise or -- worse -- be coerced into a bound nobody asked
    for. Removing it here means the rest of the query still runs.
    """
    notes: list[str] = []
    for key in ("after", "before"):
        values = filters.get(key)
        if not values:
            continue
        good: list[str] = []
        for value in values:
            if _ISO_DATE_RE.match(value):
                try:
                    date.fromisoformat(value)
                except ValueError:
                    notes.append(f"`{key}:{value}` is not a real date and was ignored.")
                    continue
                good.append(value)
            else:
                notes.append(f"`{key}:{value}` is not a date (use YYYY-MM-DD) and was ignored.")
        if good:
            filters[key] = good[:1]  # single-valued: a second bound is meaningless
        else:
            filters.pop(key, None)
    return notes


def describe(parsed: ParsedQuery) -> Sequence[str]:
    """Plain-English rendering of a parsed query, for the UI's "searching for…" line.

    The omnibar shows this under the input so an advanced query is legible without
    the user having to re-read their own syntax -- which is exactly when a typo in a
    filter name gets noticed.
    """
    parts: list[str] = []
    if parsed.phrases:
        parts.append("phrase " + ", ".join(f'"{p}"' for p in parsed.phrases))
    if parsed.terms:
        parts.append("matching " + ", ".join(parsed.terms))
    if parsed.exclusions:
        parts.append("excluding " + ", ".join(parsed.exclusions))
    for key, values in sorted(parsed.filters.items()):
        parts.append(f"{key} = {' or '.join(values)}")
    for key, values in sorted(parsed.negated_filters.items()):
        parts.append(f"{key} ≠ {' or '.join(values)}")
    return parts
