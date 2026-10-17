"""A deterministic stand-in for the OpenAI paper agent.

The fake writes exactly what it is asked for -- each draft says its type,
difficulty and number, and quotes the first words of the source -- and checks
by rules the tests control:

    FAKE_PAPER.unanswerable   draft numbers (1-based, per write call) the checker
                              says the chapter cannot answer
    FAKE_PAPER.judge_as       a difficulty the checker reports for EVERY draft,
                              to model "written as hard, judged medium"
    FAKE_PAPER.wrong_key      draft numbers whose MCQ key the checker disagrees with

Module-level, because the worker builds a new agent per paper.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modules.papers.generator import (
    TRUE_FALSE_OPTIONS,
    Check,
    Draft,
    Source,
    Usage,
    WriteRequest,
)
from app.modules.papers.models import Difficulty, PaperLanguage, QuestionType


@dataclass
class FakePaperConfig:
    unanswerable: set[int] = field(default_factory=set)
    wrong_key: set[int] = field(default_factory=set)
    judge_as: Difficulty | None = None
    requests: list[WriteRequest] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    def reset(self) -> None:
        self.unanswerable.clear()
        self.wrong_key.clear()
        self.judge_as = None
        self.requests.clear()
        self.sources.clear()


FAKE_PAPER = FakePaperConfig()

_URDU_WORDS = {
    QuestionType.MCQ: "کثیر انتخابی سوال",
    QuestionType.TRUE_FALSE: "درست یا غلط",
    QuestionType.FILL_BLANK: "خالی جگہ پُر کریں ______",
    QuestionType.SHORT: "مختصر سوال",
    QuestionType.LONG: "تفصیلی سوال",
}


class FakePaperAgent:
    def __init__(self) -> None:
        self.usage = Usage()
        self.models = {"write": "fake-write", "decide": "fake-decide"}

    async def write_questions(self, source: Source, request: WriteRequest) -> list[Draft]:
        FAKE_PAPER.requests.append(request)
        FAKE_PAPER.sources.append(source)
        self.usage.add("write", 1000, 300)
        first = source.pages[0]
        topic = " ".join(first.text.split()[:3])
        drafts: list[Draft] = []
        number = 0
        for level, count in request.counts.items():
            for _ in range(count):
                number += 1
                drafts.append(_draft(request, level, number, topic, first.printed_page))
        return drafts

    async def check_questions(self, source: Source, drafts: Sequence[Draft]) -> list[Check]:
        self.usage.add("decide", 500, 10)
        checks = []
        for draft in drafts:
            number = int(draft.text.split("#")[1].split()[0])
            judged = FAKE_PAPER.judge_as or draft.difficulty
            checks.append(
                Check(
                    answerable=0.2 if number in FAKE_PAPER.unanswerable else 0.95,
                    difficulty={judged.value: 0.9},
                    judged=judged,
                    option_agrees=((number not in FAKE_PAPER.wrong_key) if draft.options else None),
                )
            )
        return checks


def _draft(
    request: WriteRequest, level: Difficulty, number: int, topic: str, page: int | None
) -> Draft:
    urdu = request.language is PaperLanguage.URDU
    label = _URDU_WORDS[request.type] if urdu else request.type.value
    text = f"{label} {level.value} #{number} ({len(request.avoid)} avoided) on {topic}?"
    options: tuple[str, ...] = ()
    correct: int | None = None
    if request.type is QuestionType.MCQ:
        options = tuple(f"Option {letter} {number}" for letter in "ABCD")
        correct = 1
    elif request.type is QuestionType.TRUE_FALSE:
        options = TRUE_FALSE_OPTIONS[request.language]
        correct = 0
    answer = "" if request.type in (QuestionType.MCQ, QuestionType.TRUE_FALSE) else "key"
    return Draft(
        type=request.type,
        difficulty=level,
        text=text,
        options=options,
        correct_option=correct,
        answer=answer or "because",
        printed_page=page,
        chapter_number=None,
    )
