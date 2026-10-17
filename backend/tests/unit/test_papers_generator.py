"""The paper agent's rules, without a database or a network.

What these pin down:
  * "mixed" is 30/50/20 by largest remainder, and slots print objective first;
  * the writer is asked for extras, so a rejected draft does not leave a hole;
  * a draft the checker cannot answer from the chapter, or whose MCQ key the
    blind checker disagrees with, never reaches the paper;
  * a slot prefers a draft judged at its own difficulty, and says when it could not;
  * the OpenAI agent asks the option question WITHOUT showing the key, maps every
    Decisions answer back to its draft, and gives Urdu and Arabic
    true/false their own words.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.papers.agent import OpenAIPaperAgent, questions_block
from app.modules.papers.generator import (
    Check,
    Draft,
    Section,
    Slot,
    Source,
    SourcePage,
    generate,
    plan_slots,
    select,
    split_difficulty,
    well_formed,
    write_requests,
)
from app.modules.papers.models import Difficulty, PaperDifficulty, PaperLanguage, QuestionType
from tests.papers_fakes import FAKE_PAPER, FakePaperAgent

E, M, H = Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD

SOURCE = Source(
    book_title="Physics 9",
    class_name="Class 9",
    subject_name="Physics",
    chapters=((3, "Force"),),
    pages=(SourcePage(3, 42, "Newton's second law says F = ma."),),
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FAKE_PAPER.reset()


def draft(qtype: QuestionType, level: Difficulty, n: int = 1, **kw: Any) -> Draft:
    return Draft(
        type=qtype,
        difficulty=level,
        text=kw.get("text", f"{qtype.value} {level.value} #{n}"),
        options=kw.get("options", ()),
        correct_option=kw.get("correct_option"),
        answer=kw.get("answer", "key"),
        printed_page=42,
        chapter_number=3,
    )


def check(level: Difficulty, *, answerable: float = 0.9, agrees: bool | None = None) -> Check:
    return Check(answerable, {level.value: 0.9}, level, agrees)


def test_mixed_is_thirty_fifty_twenty_by_largest_remainder() -> None:
    assert split_difficulty(10, PaperDifficulty.MIXED) == {E: 3, M: 5, H: 2}
    assert split_difficulty(7, PaperDifficulty.MIXED) == {E: 2, M: 4, H: 1}
    assert split_difficulty(1, PaperDifficulty.MIXED) == {M: 1}, "one question is medium"
    assert split_difficulty(4, PaperDifficulty.HARD) == {H: 4}


def test_slots_print_objective_first_then_easy_to_hard() -> None:
    slots = plan_slots(
        [Section(QuestionType.LONG, 1, 5), Section(QuestionType.MCQ, 3, 1)],
        PaperDifficulty.MIXED,
    )
    assert [(s.type, s.difficulty) for s in slots] == [
        (QuestionType.MCQ, E),
        (QuestionType.MCQ, M),
        (QuestionType.MCQ, H),
        (QuestionType.LONG, M),
    ]
    assert [s.marks for s in slots] == [1, 1, 1, 5]


def test_the_writer_is_asked_for_extras_per_difficulty() -> None:
    slots = plan_slots([Section(QuestionType.SHORT, 10, 2)], PaperDifficulty.MIXED)
    (request,) = write_requests(slots, PaperLanguage.URDU, avoid=["old"])
    assert request.counts == {E: 5, M: 7, H: 3}, "3+2, 5+2, 2+1"
    assert request.language is PaperLanguage.URDU and request.avoid == ("old",)


def test_rejected_drafts_never_reach_the_paper() -> None:
    mcq = {"options": ("a", "b", "c", "d"), "correct_option": 0}
    slots = [Slot(QuestionType.MCQ, E, 1), Slot(QuestionType.MCQ, E, 1)]
    drafts = [
        draft(QuestionType.MCQ, E, 1, **mcq),
        draft(QuestionType.MCQ, E, 2, **mcq),
        draft(QuestionType.MCQ, E, 3, **mcq),
    ]
    checks = [
        check(E, answerable=0.3, agrees=True),  # the chapter does not answer it
        check(E, agrees=False),  # the blind checker picked another option
        check(E, agrees=True),
    ]
    result = select(slots, drafts, checks)
    assert [c.draft.text for c in result.chosen] == ["mcq easy #3"]
    assert result.passed == 1
    assert result.issues[0]["code"] == "missing_questions"
    assert result.issues[0]["count"] == 1


def test_a_slot_prefers_its_own_difficulty_and_reports_a_mismatch() -> None:
    slots = [Slot(QuestionType.SHORT, H, 2), Slot(QuestionType.SHORT, E, 2)]
    drafts = [draft(QuestionType.SHORT, E, 1), draft(QuestionType.SHORT, H, 2)]
    # The second was WRITTEN hard but judged medium; the first is truly easy.
    checks = [check(E), check(M)]
    result = select(slots, drafts, checks)
    assert [(c.slot.difficulty, c.difficulty) for c in result.chosen] == [(H, M), (E, E)]
    assert [i["code"] for i in result.issues] == ["difficulty_mismatch"]
    assert not result.complete


def test_malformed_and_duplicate_drafts_are_dropped_before_checking() -> None:
    good = draft(QuestionType.MCQ, E, 1, options=("a", "b", "c", "d"), correct_option=2)
    same_options = draft(QuestionType.MCQ, E, 2, options=("a", "A", "c", "d"), correct_option=0)
    no_key = draft(QuestionType.SHORT, E, 3, answer="  ")
    assert well_formed(good)
    assert not well_formed(same_options), "options must differ"
    assert not well_formed(no_key), "a subjective question needs its key"


async def test_generate_writes_checks_and_fills_every_slot() -> None:
    slots = plan_slots(
        [Section(QuestionType.MCQ, 5, 1), Section(QuestionType.SHORT, 2, 2)],
        PaperDifficulty.MIXED,
    )
    FAKE_PAPER.unanswerable.add(1)
    result = await generate(SOURCE, slots, PaperLanguage.ENGLISH, FakePaperAgent())
    assert len(result.chosen) == len(slots)
    assert result.complete, result.issues
    assert all("#1 " not in c.draft.text for c in result.chosen), "the rejected draft"
    assert {r.type for r in FAKE_PAPER.requests} == {QuestionType.MCQ, QuestionType.SHORT}


async def test_a_question_already_on_the_paper_is_never_chosen_again() -> None:
    agent = FakePaperAgent()
    slots = [Slot(QuestionType.SHORT, E, 2)]
    first = await generate(SOURCE, slots, PaperLanguage.ENGLISH, agent)
    taken = first.chosen[0].draft.text
    again = await generate(SOURCE, slots, PaperLanguage.ENGLISH, agent, avoid=[taken])
    assert FAKE_PAPER.requests[-1].avoid == (taken,)
    assert again.chosen[0].draft.text != taken


async def test_truncated_chapters_are_reported() -> None:
    source = dataclasses.replace(SOURCE, truncated=True)
    result = await generate(
        source, [Slot(QuestionType.SHORT, E, 2)], PaperLanguage.ENGLISH, FakePaperAgent()
    )
    assert [i["code"] for i in result.issues] == ["source_truncated"]


# -- the OpenAI agent, against stub clients --------------------------------------


def _choice(value: str, probabilities: dict[str, float] | None = None) -> Any:
    probabilities = probabilities or {value: 0.9}
    return SimpleNamespace(
        type="choice",
        choice=value,
        confidence=probabilities.get(value, 0.9),
        probabilities=[SimpleNamespace(value=k, probability=v) for k, v in probabilities.items()],
    )


def _predicate(p: float) -> Any:
    return SimpleNamespace(type="predicate", probability=p)


async def test_the_openai_checker_asks_blind_and_maps_answers_back() -> None:
    sent: list[dict[str, Any]] = []

    async def create(**body: Any) -> Any:
        sent.append(body)
        names = [q["name"] for q in body["questions"]]
        answers = []
        for name in names:
            if name.endswith(".difficulty"):
                answers.append(_choice("hard" if name.startswith("Q2") else "easy"))
            elif name.endswith(".option"):
                answers.append(_choice("B" if name.startswith("Q1") else "false"))
            else:
                answers.append(_predicate(0.4 if name.startswith("Q2") else 0.97))
        return SimpleNamespace(
            answers=answers, usage=SimpleNamespace(input_tokens=100, output_tokens=5)
        )

    client = SimpleNamespace(decisions=SimpleNamespace(create=create))
    agent = OpenAIPaperAgent(Settings(OPENAI_API_KEY=""), client=client)  # type: ignore[arg-type]
    drafts = [
        draft(QuestionType.MCQ, E, 1, options=("w", "x", "y", "z"), correct_option=1),
        draft(QuestionType.SHORT, H, 2),
        draft(QuestionType.TRUE_FALSE, E, 3, options=("True", "False"), correct_option=0),
    ]
    checks = await agent.check_questions(SOURCE, drafts)

    assert [c.judged for c in checks] == [E, H, E]
    assert [c.answerable for c in checks] == [0.97, 0.4, 0.97]
    assert [c.option_agrees for c in checks] == [True, None, False]
    blind, keyed = sent
    blind_text = blind["input"][0]["content"][0]["text"]
    keyed_text = keyed["input"][0]["content"][0]["text"]
    assert "Answer key" not in blind_text, "the option question never sees the key"
    assert "Answer key: B. key" in keyed_text
    assert [q["name"] for q in keyed["questions"]] == [
        "Q1.answerable",
        "Q2.answerable",
        "Q3.answerable",
    ]
    assert agent.usage.calls == {"decide": 2}


@pytest.mark.parametrize(
    ("language", "words", "script"),
    [
        (PaperLanguage.URDU, ("درست", "غلط"), "in Urdu script"),
        (PaperLanguage.ARABIC, ("صحيح", "خطأ"), "in Arabic script"),
    ],
)
async def test_the_openai_writer_gives_true_false_the_papers_own_words(
    language: PaperLanguage, words: tuple[str, str], script: str
) -> None:
    sent: list[dict[str, Any]] = []

    async def create(**body: Any) -> Any:
        sent.append(body)
        payload = {
            "questions": [
                {
                    "difficulty": "easy",
                    "text": "پانی سو درجے پر ابلتا ہے",
                    "options": ["ignored"],
                    "correct_option": 0,
                    "answer": "درست",
                    "printed_page": 12,
                    "chapter_number": 1,
                }
            ]
        }
        return SimpleNamespace(
            output_text=json.dumps(payload),
            usage=SimpleNamespace(input_tokens=2000, output_tokens=100),
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    agent = OpenAIPaperAgent(Settings(OPENAI_API_KEY=""), client=client)  # type: ignore[arg-type]
    request = write_requests([Slot(QuestionType.TRUE_FALSE, E, 1)], language)[0]
    (out,) = await agent.write_questions(SOURCE, request)

    assert out.options == words
    assert out.correct_option == 0 and out.printed_page == 12
    body = sent[0]
    assert body["text"]["format"]["strict"] is True
    task = body["input"][0]["content"][1]["text"]
    assert script in task and "Write exactly: 2 easy." in task


def test_the_questions_block_letters_mcq_options() -> None:
    block = questions_block(
        [draft(QuestionType.MCQ, E, 1, options=("w", "x", "y", "z"), correct_option=3)],
        with_keys=True,
    )
    assert "A) w" in block and "D) z" in block and "Answer key: D. key" in block
