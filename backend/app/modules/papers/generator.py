"""The paper agent's procedure: plan, write, check, select.

WHY THIS FILE EXISTS
    This is the paper agent's reasoning written down as code -- how a request
    becomes slots, how many drafts to ask for, which evidence rejects a draft, and
    which draft fills which slot. It takes chapter text in and returns plain data
    out -- no database, no network -- so every rule is tested with a fake agent.

THE STEPS
    1. PLAN     sections ("10 MCQs at 1 mark") x the paper's difficulty become
                SLOTS, each with one difficulty. "mixed" splits a section 30/50/20
                (easy/medium/hard) by largest remainder.
    2. WRITE    one writing call per question type, in parallel, from the chapter
                text only. Each asks for ~40% more drafts than slots, so a draft
                the checks reject does not leave a hole.
    3. CHECK    every draft goes to the Decisions API: is it answerable from the
                chapter (and is the key right)? how hard is it really? and, for
                MCQ / true-false, which option is correct -- which must agree with
                the writer's key.
    4. SELECT   each slot takes the best passing draft of its type: the checker's
                difficulty matching the slot first, then the nearest difficulty.
                A slot filled at another difficulty, or not filled at all, is an
                issue, and any issue makes the paper NEEDS_REVIEW.

THE CHAPTER IS UNTRUSTED INPUT
    It reaches the models as evidence only, and every answer comes back through a
    schema or a closed choice -- see `agent.py`.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.papers.models import (
    Difficulty,
    PaperDifficulty,
    PaperLanguage,
    QuestionType,
)

MIXED_SHARES: dict[Difficulty, float] = {
    Difficulty.EASY: 0.3,
    Difficulty.MEDIUM: 0.5,
    Difficulty.HARD: 0.2,
}
DEFAULT_MARKS: dict[QuestionType, int] = {
    QuestionType.MCQ: 1,
    QuestionType.TRUE_FALSE: 1,
    QuestionType.FILL_BLANK: 1,
    QuestionType.SHORT: 2,
    QuestionType.LONG: 5,
}
TYPE_ORDER: tuple[QuestionType, ...] = (
    QuestionType.MCQ,
    QuestionType.TRUE_FALSE,
    QuestionType.FILL_BLANK,
    QuestionType.SHORT,
    QuestionType.LONG,
)
"""Section order on the paper: objective first, as Pakistani papers print them."""

ANSWERABLE_MIN = 0.6
"""Below this the checker does not believe the chapter answers the question."""
_EXTRA_SHARE = 0.4
_DIFFICULTY_RANK = {Difficulty.EASY: 0, Difficulty.MEDIUM: 1, Difficulty.HARD: 2}

TRUE_FALSE_OPTIONS: dict[PaperLanguage, tuple[str, str]] = {
    PaperLanguage.ENGLISH: ("True", "False"),
    PaperLanguage.URDU: ("درست", "غلط"),
    PaperLanguage.ARABIC: ("صحيح", "خطأ"),
}


# -- inputs --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Section:
    type: QuestionType
    count: int
    marks: int


@dataclass(frozen=True, slots=True)
class Slot:
    type: QuestionType
    difficulty: Difficulty
    marks: int


@dataclass(frozen=True, slots=True)
class SourcePage:
    chapter_number: int
    printed_page: int | None
    text: str


@dataclass(frozen=True, slots=True)
class Source:
    """The chapters a paper is written from, as the models see them."""

    book_title: str
    class_name: str
    subject_name: str | None
    chapters: tuple[tuple[int, str], ...]
    """(number, title) of each chapter, in order."""
    pages: tuple[SourcePage, ...]
    truncated: bool = False
    """True when the chapters were longer than the models are given."""


# -- what the agent returns ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriteRequest:
    type: QuestionType
    counts: dict[Difficulty, int]
    """Drafts wanted at each difficulty -- already including the extras."""
    language: PaperLanguage
    avoid: tuple[str, ...] = ()
    """Question texts already on the paper: never write these again."""


@dataclass(frozen=True, slots=True)
class Draft:
    type: QuestionType
    difficulty: Difficulty
    """What the writer meant it to be."""
    text: str
    options: tuple[str, ...]
    correct_option: int | None
    answer: str
    printed_page: int | None
    chapter_number: int | None


@dataclass(frozen=True, slots=True)
class Check:
    answerable: float
    difficulty: dict[str, float]
    """Probability of each difficulty, by value."""
    judged: Difficulty | None
    option_agrees: bool | None
    """None for a type without options, or when the checker would not choose."""

    def as_json(self) -> dict[str, Any]:
        return {
            "answerable": round(self.answerable, 3),
            "difficulty": {k: round(v, 3) for k, v in self.difficulty.items()},
            "judged": self.judged.value if self.judged else None,
            "option_agrees": self.option_agrees,
        }


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, input_tokens: int, output_tokens: int = 0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls[kind] = self.calls.get(kind, 0) + 1


class PaperAgent(Protocol):
    usage: Usage
    models: dict[str, str]

    async def write_questions(self, source: Source, request: WriteRequest) -> list[Draft]: ...

    async def check_questions(self, source: Source, drafts: Sequence[Draft]) -> list[Check]:
        """One `Check` per draft, in order."""
        ...


# -- result ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chosen:
    slot: Slot
    draft: Draft
    check: Check

    @property
    def difficulty(self) -> Difficulty:
        """What the question IS: the checker's verdict over the writer's intent."""
        return self.check.judged or self.draft.difficulty


@dataclass
class Generation:
    chosen: list[Chosen]
    issues: list[dict[str, Any]]
    written: int
    passed: int

    @property
    def complete(self) -> bool:
        return not self.issues


# -- 1. plan ---------------------------------------------------------------------


def split_difficulty(count: int, difficulty: PaperDifficulty) -> dict[Difficulty, int]:
    """How many of `count` questions are easy, medium and hard."""
    if difficulty is not PaperDifficulty.MIXED:
        return {Difficulty(difficulty.value): count}
    raw = {d: count * share for d, share in MIXED_SHARES.items()}
    split = {d: math.floor(v) for d, v in raw.items()}
    # Largest remainder; ties go to medium, then easy -- the safer middle.
    order = sorted(
        raw,
        key=lambda d: (raw[d] - split[d], d is Difficulty.MEDIUM, d is Difficulty.EASY),
        reverse=True,
    )
    for d in order[: count - sum(split.values())]:
        split[d] += 1
    return {d: n for d, n in split.items() if n}


def plan_slots(sections: Sequence[Section], difficulty: PaperDifficulty) -> list[Slot]:
    """Every slot on the paper, in print order: by type, then easy to hard."""
    by_type = {s.type: s for s in sections if s.count > 0}
    slots: list[Slot] = []
    for qtype in TYPE_ORDER:
        section = by_type.get(qtype)
        if section is None:
            continue
        for level, n in sorted(
            split_difficulty(section.count, difficulty).items(),
            key=lambda item: _DIFFICULTY_RANK[item[0]],
        ):
            slots.extend(Slot(qtype, level, section.marks) for _ in range(n))
    return slots


def write_requests(
    slots: Sequence[Slot], language: PaperLanguage, avoid: Sequence[str] = ()
) -> list[WriteRequest]:
    """One request per type, asking for each difficulty's slots plus extras."""
    wanted: dict[QuestionType, dict[Difficulty, int]] = {}
    for slot in slots:
        counts = wanted.setdefault(slot.type, {})
        counts[slot.difficulty] = counts.get(slot.difficulty, 0) + 1
    return [
        WriteRequest(
            type=qtype,
            counts={d: n + max(1, math.ceil(n * _EXTRA_SHARE)) for d, n in counts.items()},
            language=language,
            avoid=tuple(avoid),
        )
        for qtype, counts in wanted.items()
    ]


# -- 3/4. check and select -------------------------------------------------------


def well_formed(draft: Draft) -> bool:
    """The structural rules a draft must meet before a model is asked about it."""
    if not draft.text.strip():
        return False
    if draft.type is QuestionType.MCQ:
        options = [o.strip() for o in draft.options]
        return (
            len(options) == 4
            and all(options)
            and len({o.casefold() for o in options}) == 4
            and draft.correct_option in range(4)
        )
    if draft.type is QuestionType.TRUE_FALSE:
        return draft.correct_option in (0, 1)
    return bool(draft.answer.strip())


def passes(draft: Draft, check: Check) -> bool:
    return check.answerable >= ANSWERABLE_MIN and check.option_agrees is not False


def select(slots: Sequence[Slot], drafts: Sequence[Draft], checks: Sequence[Check]) -> Generation:
    """Fill every slot it can from the passing drafts."""
    pool: dict[QuestionType, list[tuple[Draft, Check]]] = {}
    for draft, check in zip(drafts, checks, strict=True):
        if passes(draft, check):
            pool.setdefault(draft.type, []).append((draft, check))
    passed = sum(len(v) for v in pool.values())

    chosen: list[Chosen] = []
    missing: dict[QuestionType, int] = {}
    off_level = 0
    for slot in slots:
        candidates = pool.get(slot.type, [])
        if not candidates:
            missing[slot.type] = missing.get(slot.type, 0) + 1
            continue
        best = min(
            range(len(candidates)),
            key=lambda i: _fit(slot, candidates[i][0], candidates[i][1]),
        )
        draft, check = candidates.pop(best)
        pick = Chosen(slot, draft, check)
        if pick.difficulty is not slot.difficulty:
            off_level += 1
        chosen.append(pick)

    issues: list[dict[str, Any]] = []
    for qtype, n in missing.items():
        issues.append(
            {
                "code": "missing_questions",
                "message": f"{n} {qtype.value} question(s) could not be written from "
                "these chapters and passed the checks.",
                "type": qtype.value,
                "count": n,
            }
        )
    if off_level:
        issues.append(
            {
                "code": "difficulty_mismatch",
                "message": f"{off_level} question(s) were judged a different difficulty "
                "than their slot asked for.",
                "count": off_level,
            }
        )
    return Generation(chosen=chosen, issues=issues, written=len(drafts), passed=passed)


def _fit(slot: Slot, draft: Draft, check: Check) -> tuple[int, int, float]:
    judged = check.judged or draft.difficulty
    return (
        abs(_DIFFICULTY_RANK[judged] - _DIFFICULTY_RANK[slot.difficulty]),
        0 if draft.difficulty is slot.difficulty else 1,
        -check.answerable,
    )


# -- the whole run ---------------------------------------------------------------


async def generate(
    source: Source,
    slots: Sequence[Slot],
    language: PaperLanguage,
    agent: PaperAgent,
    *,
    avoid: Sequence[str] = (),
) -> Generation:
    requests = write_requests(slots, language, avoid)
    written = await asyncio.gather(*(agent.write_questions(source, r) for r in requests))
    drafts = [d for batch in written for d in batch if well_formed(d)]
    seen: set[str] = {" ".join(a.casefold().split()) for a in avoid}
    unique: list[Draft] = []
    for draft in drafts:
        key = " ".join(draft.text.casefold().split())
        if key not in seen:
            seen.add(key)
            unique.append(draft)
    checks = await agent.check_questions(source, unique) if unique else []
    result = select(slots, unique, checks)
    if source.truncated:
        result.issues.append(
            {
                "code": "source_truncated",
                "message": "The chapters were too long to read whole; questions come "
                "from their first pages.",
            }
        )
    return result
