"""The book agent's procedure, against a fake model backend -- no database, no network.

What is worth pinning down:

  * PHOTOS IN ANY ORDER come out in printed-page order.
  * An UNNUMBERED page is placed by evidence (its PDF neighbour, or a continuity
    decision) before upload order is ever used.
  * The chapter check: an upload filed under the wrong chapter, or carrying a page
    from another chapter, is NEEDS_REVIEW -- never silently READY.
  * Missing and duplicated page numbers are reported.
  * A typeset PDF never reaches the vision model.
  * BATCH READING: readings collected from a batch are used as they are, a page
    the batch did not answer is read live, and the real agent's batch requests
    are the live request, split under the file cap and mapped back by custom id.
  * BATCH EMBEDDING: a run that leaves embedding to a batch makes no embedding
    call, and the real agent's embedding batch maps vectors back by chunk id,
    dropping any it cannot store.
  * READING A BOOK'S COVER goes to the provider and model `.env` names, asks for
    a non-streamed answer (kie.ai streams by default), and offers only the
    campus's classes and subjects.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from openai import APIStatusError, AuthenticationError, NotFoundError

from app.core.config import Settings
from app.modules.books import agent as agent_module
from app.modules.books.agent import (
    AgentNotConfiguredError,
    BookContext,
    ChapterRef,
    CompatibleFrontMatterReader,
    EmbedRequest,
    FrontPage,
    OpenAIBookAgent,
    PageReading,
    Passage,
    ReadRequest,
)
from app.modules.books.ingest import guess_printed_page_number, sniff_kind, text_layer_is_usable
from app.modules.books.models import ChapterStatus, FileKind, PageMethod, PagePlacement
from app.modules.books.pipeline import (
    SourceFile,
    WorkingPage,
    chunk_pages,
    pages_to_read,
    run_pipeline,
)
from tests.books_fakes import PHOTO_PAGES, FakeBookAgent, PhotoPage, make_pdf, make_photo

CHAPTERS = (ChapterRef(1, "Numbers"), ChapterRef(2, "Fractions"), ChapterRef(3, "Decimals"))

BODY = (
    "Fractions describe parts of a whole. The numerator counts the parts we have, "
    "and the denominator counts the equal parts the whole is divided into. "
)


def ctx(declared: int = 2) -> BookContext:
    return BookContext(
        title="New Countdown",
        class_name="Grade 5",
        publisher="Oxford",
        version="3rd Edition",
        chapters=CHAPTERS,
        declared=CHAPTERS[declared - 1],
    )


def photo(index: int, printed: int | None, text: str) -> SourceFile:
    PHOTO_PAGES[index] = PhotoPage(printed, text)
    return SourceFile(uuid4(), FileKind.IMAGE, index, make_photo(index))


def by_position(pages: list[WorkingPage]) -> list[int | None]:
    return [p.printed_page_number for p in sorted(pages, key=lambda p: p.position)]


async def test_photos_uploaded_out_of_order_come_out_in_page_order() -> None:
    files = [
        photo(1, 23, f"[CH 2] {BODY} third"),
        photo(2, 21, f"[CH 2] [OPENS] Chapter 2 Fractions {BODY}"),
        photo(3, 22, f"[CH 2] {BODY} second"),
    ]
    result = await run_pipeline(ctx(), files, FakeBookAgent())

    assert by_position(result.pages) == [21, 22, 23]
    assert {p.placement for p in result.pages} == {PagePlacement.PRINTED_NUMBER}
    assert result.status is ChapterStatus.READY, result.report["issues"]
    assert result.report["matches_declared"] is True
    assert result.report["vision_pages"] == 3


async def test_an_unnumbered_photo_is_placed_by_a_continuity_decision() -> None:
    agent = FakeBookAgent()
    files = [
        photo(11, 31, f"[CH 2] {BODY}"),
        photo(12, None, f"[CH 2] [AFTER 31] a full-page diagram {BODY}"),
        photo(13, 33, f"[CH 2] {BODY}"),
    ]
    result = await run_pipeline(ctx(), files, agent)

    ordered = sorted(result.pages, key=lambda p: p.position)
    assert [p.printed_page_number for p in ordered] == [31, None, 33]
    assert ordered[1].placement is PagePlacement.AGENT
    assert agent.placement_questions == [ordered[1].label]
    # The unnumbered page fills the gap between 31 and 33 -- nothing is missing.
    assert not [i for i in result.report["issues"] if i["code"] == "missing_pages"]


async def test_a_typeset_pdf_is_read_from_its_text_layer_and_kept_in_pdf_order() -> None:
    agent = FakeBookAgent()
    pdf = make_pdf(
        [
            (None, f"[CH 2] [OPENS] Chapter 2: Fractions\n{BODY}\n{BODY}"),
            (41, f"[CH 2]\n{BODY}\n{BODY}"),
            (42, f"[CH 2]\n{BODY}\n{BODY}"),
        ]
    )
    result = await run_pipeline(ctx(), [SourceFile(uuid4(), FileKind.PDF, 1, pdf)], agent)

    assert agent.usage.calls.get("read") is None  # the vision model was never called
    assert {p.method for p in result.pages} == {PageMethod.TEXT_LAYER}
    assert by_position(result.pages) == [None, 41, 42]
    assert result.pages[0].placement is PagePlacement.PDF_ORDER
    assert result.status is ChapterStatus.READY, result.report["issues"]


async def test_an_upload_of_the_wrong_chapter_needs_review() -> None:
    files = [photo(21, 50, f"[CH 3] [OPENS] Chapter 3 Decimals {BODY}")]
    result = await run_pipeline(ctx(declared=2), files, FakeBookAgent())

    assert result.status is ChapterStatus.NEEDS_REVIEW
    assert result.report["detected_chapter_number"] == 3
    assert result.report["matches_declared"] is False
    codes = [i["code"] for i in result.report["issues"]]
    assert "chapter_mismatch" in codes
    assert "foreign_pages" in codes


async def test_missing_and_duplicate_page_numbers_are_reported() -> None:
    files = [
        photo(31, 10, f"[CH 2] [OPENS] {BODY}"),
        photo(32, 11, f"[CH 2] {BODY} a"),
        photo(33, 11, f"[CH 2] {BODY} b"),
        photo(34, 14, f"[CH 2] {BODY} c"),
    ]
    result = await run_pipeline(ctx(), files, FakeBookAgent())

    issues = {i["code"]: i for i in result.report["issues"]}
    assert "duplicate_page_number" in issues
    assert issues["missing_pages"]["message"].startswith("Nothing was uploaded for pages 12-13")
    assert result.status is ChapterStatus.NEEDS_REVIEW


async def test_chunks_cover_every_page_and_carry_their_page_numbers() -> None:
    files = [photo(40 + i, 60 + i, f"[CH 2] {BODY * 6} page {60 + i}") for i in range(5)]
    result = await run_pipeline(ctx(), files, FakeBookAgent())

    assert len(result.chunks) > 1
    assert result.chunks[0].printed_start == 60
    assert result.chunks[-1].printed_end == 64
    assert all(len(c.embedding) == 1536 for c in result.chunks)
    covered = {pos for c in result.chunks for pos in range(c.page_start, c.page_end + 1)}
    assert covered == {1, 2, 3, 4, 5}


def test_chunking_never_emits_the_overlap_alone() -> None:
    page = WorkingPage(
        label="P1",
        file_id=uuid4(),
        file_kind=FileKind.IMAGE,
        file_is_single=True,
        source_index=0,
        upload_index=0,
        image=b"",
        image_type="image/jpeg",
        text=("x" * 2000) + "\n\n" + ("short tail"),
        printed_page_number=1,
        position=1,
    )
    chunks = chunk_pages([page])
    assert [c.content[-10:] for c in chunks] == ["short tail"]


def test_ingest_helpers() -> None:
    assert sniff_kind(b"%PDF-1.7 ...")[0] is FileKind.PDF
    assert sniff_kind(make_photo(1)) == (FileKind.IMAGE, "image/jpeg")
    assert guess_printed_page_number("Chapter 2\nbody text\n- 42 -") == 42
    assert guess_printed_page_number("Table 12 shows\nthe results") is None
    assert not text_layer_is_usable("" * 200)  # private-use glyph garbage
    assert text_layer_is_usable(BODY * 3)


# -- batch reading -------------------------------------------------------------


async def test_batch_readings_are_used_and_an_unanswered_page_is_read_live() -> None:
    files = [
        photo(41, 31, f"[CH 2] [OPENS] Chapter 2 Fractions {BODY}"),
        photo(42, 32, f"[CH 2] {BODY} second"),
        SourceFile(uuid4(), FileKind.PDF, 43, make_pdf([(33, f"[CH 2] {BODY * 3}")])),
    ]
    requests = await pages_to_read(files)
    assert len(requests) == 2, "the typeset PDF page needs no vision read"

    answered = requests[0]
    readings = {answered.key: PageReading(printed_page_number=31, text="From the batch.")}
    agent = FakeBookAgent()
    result = await run_pipeline(ctx(), files, agent, readings)

    assert by_position(result.pages) == [31, 32, 33]
    assert result.pages[0].text == "From the batch."
    assert result.report["vision_pages"] == 2
    assert result.report["batch_read_pages"] == 1
    assert result.report["batch_fallback_pages"] == 1
    assert agent.usage.calls["read"] == 1, "only the unanswered page is read live"


class _StubClient:
    """Just enough of AsyncOpenAI for the batch methods."""

    def __init__(self) -> None:
        self.uploads: list[bytes] = []
        self.endpoints: list[str] = []
        self.outputs: dict[str, str] = {}
        self.deleted: list[str] = []
        self.files = SimpleNamespace(
            create=self._upload, content=self._content, delete=self._delete
        )
        self.batches = SimpleNamespace(create=self._batch, retrieve=self._retrieve)

    async def _upload(self, *, file: tuple[str, bytes, str], purpose: str) -> Any:
        assert purpose == "batch"
        self.uploads.append(file[1])
        return SimpleNamespace(id=f"file_{len(self.uploads)}")

    async def _batch(self, **kwargs: Any) -> Any:
        assert kwargs["completion_window"] == "24h"
        self.endpoints.append(kwargs["endpoint"])
        return SimpleNamespace(id=kwargs["input_file_id"].replace("file", "batch"))

    async def _retrieve(self, batch_id: str) -> Any:
        number = batch_id.split("_")[1]
        return SimpleNamespace(
            id=batch_id,
            status="completed",
            input_file_id=f"file_{number}",
            output_file_id=f"out_{number}",
            error_file_id=None,
        )

    async def _content(self, file_id: str) -> Any:
        return SimpleNamespace(text=self.outputs[file_id])

    async def _delete(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _output_line(custom_id: str, status: int, text: str) -> str:
    body = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    return json.dumps({"custom_id": custom_id, "response": {"status_code": status, "body": body}})


async def test_the_openai_agent_batches_reads_and_maps_results_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StubClient()
    agent = OpenAIBookAgent(Settings(OPENAI_API_KEY=""), client=client)  # type: ignore[arg-type]
    pages = [ReadRequest(f"file:{i}", make_photo(i), "image/jpeg") for i in range(3)]

    one_line = len(json.dumps({"body": agent._read_body(pages[0].image, "image/jpeg")}))
    monkeypatch.setattr(
        agent_module, "_BATCH_FILE_BYTES", one_line * 2 + 500
    )  # two lines fit, three do not
    batch_ids = await agent.submit_reads(pages, label="chapter")
    assert batch_ids == ["batch_1", "batch_2"], "a file over the cap is split"
    assert client.endpoints == ["/v1/responses", "/v1/responses"]

    first = json.loads(client.uploads[0].splitlines()[0])
    assert first["custom_id"] == "file:0"
    assert first["url"] == "/v1/responses"
    assert first["body"] == agent._read_body(pages[0].image, "image/jpeg")
    assert first["body"]["text"]["format"]["strict"] is True

    client.outputs["out_1"] = "\n".join(
        [
            _output_line("file:0", 200, '{"printed_page_number": 7, "text": "Seven"}'),
            _output_line("file:1", 500, ""),
        ]
    )
    client.outputs["out_2"] = _output_line("file:2", 200, "not json")
    assert await agent.batches_ready(batch_ids)
    readings = await agent.collect_reads(batch_ids)

    assert readings == {"file:0": PageReading(printed_page_number=7, text="Seven")}
    assert agent.usage.calls == {"read_batch": 2}
    assert agent.usage.input_tokens == 2000

    await agent.discard_batches(batch_ids)
    assert client.deleted == ["file_1", "out_1", "file_2", "out_2"]


# -- batch embedding -----------------------------------------------------------


async def test_a_run_that_leaves_embedding_to_a_batch_embeds_nothing() -> None:
    files = [SourceFile(uuid4(), FileKind.PDF, 0, make_pdf([(21, f"[CH 2] [OPENS] {BODY * 3}")]))]
    agent = FakeBookAgent()
    result = await run_pipeline(ctx(), files, agent, embed=False)

    assert result.status is ChapterStatus.READY, result.report["issues"]
    assert result.chunks and all(c.embedding == [] for c in result.chunks)
    assert "embed" not in agent.usage.calls


def _embedding_line(custom_id: str, status: int, vector: list[float]) -> str:
    body = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": vector}],
        "usage": {"prompt_tokens": 120, "total_tokens": 120},
    }
    return json.dumps({"custom_id": custom_id, "response": {"status_code": status, "body": body}})


async def test_the_openai_agent_batches_embeddings_and_maps_them_back_by_chunk() -> None:
    client = _StubClient()
    settings = Settings(OPENAI_API_KEY="", BOOKS_EMBEDDING_DIMENSIONS=3)
    agent = OpenAIBookAgent(settings, client=client)  # type: ignore[arg-type]
    chunks = [EmbedRequest(f"chunk-{i}", f"Passage {i}") for i in range(4)]

    batch_ids = await agent.submit_embeddings(chunks, label="chapter-embed")
    assert batch_ids == ["batch_1"] and client.endpoints == ["/v1/embeddings"]
    lines = [json.loads(line) for line in client.uploads[0].splitlines()]
    assert [line["custom_id"] for line in lines] == ["chunk-0", "chunk-1", "chunk-2", "chunk-3"]
    assert lines[0]["url"] == "/v1/embeddings"
    assert lines[0]["body"] == {
        "model": "text-embedding-3-small",
        "input": "Passage 0",
        "dimensions": 3,
    }

    client.outputs["out_1"] = "\n".join(
        [
            _embedding_line("chunk-0", 200, [0.1, 0.2, 0.3]),
            _embedding_line("chunk-1", 429, [0.1, 0.2, 0.3]),  # not answered
            _embedding_line("chunk-2", 200, [0.1, 0.2]),  # wrong size for vector(n)
            "not json",
            _embedding_line("chunk-3", 200, [1, 0, 0]),
        ]
    )
    assert await agent.batches_ready(batch_ids)
    vectors = await agent.collect_embeddings(batch_ids)

    assert vectors == {"chunk-0": [0.1, 0.2, 0.3], "chunk-3": [1.0, 0.0, 0.0]}
    assert agent.usage.calls == {"embed_batch": 2}
    assert agent.usage.input_tokens == 240


async def test_the_openai_agent_answers_only_with_citations_it_was_given() -> None:
    sent: list[dict[str, Any]] = []

    async def create(**body: Any) -> Any:
        sent.append(body)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "found": True,
                    "answer": "Force is mass times acceleration [2].",
                    "citations": [2, 7, 2],
                }
            ),
            usage=SimpleNamespace(input_tokens=900, output_tokens=40),
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    agent = OpenAIBookAgent(Settings(OPENAI_API_KEY=""), client=client)  # type: ignore[arg-type]
    passages = [
        Passage(1, "Physics 9, Ch 2: Motion, p. 30", "Motion is a change of position."),
        Passage(2, "Physics 9, Ch 3: Force, p. 42", "Newton's second law: F = ma."),
    ]
    answer = await agent.answer_question("What is Newton's second law?", passages)

    assert answer.found is True
    assert answer.citations == [2], "unknown passage numbers and repeats are dropped"
    (body,) = sent
    assert body["model"] == agent.answer_model
    assert body["text"]["format"]["strict"] is True
    prompt = body["input"][0]["content"][0]["text"]
    assert "[2] Physics 9, Ch 3: Force, p. 42\nNewton's second law: F = ma." in prompt
    assert prompt.endswith("QUESTION\nWhat is Newton's second law?")
    assert agent.usage.calls == {"answer": 1}


def cover_client(models: Sequence[str] = (), **apis: Any) -> Any:
    """A fake OpenAI-compatible server: `responses=` / `chat=` are `create`
    functions, `models` what GET /models lists. Each gets its own base URL, so the
    reader's per-provider memory never carries over between tests."""

    async def listing() -> AsyncIterator[Any]:
        for model_id in models:
            yield SimpleNamespace(id=model_id)

    client = SimpleNamespace(
        base_url=f"http://provider-{uuid4()}/v1/",
        models=SimpleNamespace(list=listing),
    )
    if "responses" in apis:
        client.responses = SimpleNamespace(create=apis["responses"])
    if "chat" in apis:
        client.chat = SimpleNamespace(completions=SimpleNamespace(create=apis["chat"]))
    return client


def chat_answer(content: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=4000, completion_tokens=60),
    )


def not_found(api: str) -> NotFoundError:
    request = httpx2.Request("POST", f"http://provider/v1/{api}")
    return NotFoundError("Not Found", response=httpx2.Response(404, request=request), body=None)


def test_the_cover_reader_uses_the_provider_and_model_named_in_settings() -> None:
    def settings(**values: Any) -> Settings:
        return Settings(_env_file=None, **values)  # not the dev .env

    def reader(**values: Any) -> CompatibleFrontMatterReader:
        made = agent_module.front_matter_reader(settings(**values))
        assert isinstance(made, CompatibleFrontMatterReader)
        return made

    kie = reader(BOOKS_SCAN_PROVIDER="kie", BOOKS_SCAN_MODEL="gpt-6-sol", KIE_API_TOKEN="k")
    assert (kie.model, kie.api) == ("gpt-6-sol", "auto")
    assert str(kie.client.base_url).startswith("https://api.kie.ai/openai/v1")

    openai = reader(BOOKS_SCAN_PROVIDER="openai", BOOKS_SCAN_MODEL="gpt-5.4", OPENAI_API_KEY="o")
    assert str(openai.client.base_url).startswith("https://api.openai.com")

    # Any OpenAI-compatible server, in the API it speaks; a local one needs no key.
    local = reader(
        BOOKS_SCAN_PROVIDER="custom",
        BOOKS_SCAN_BASE_URL="http://localhost:11434/v1",
        BOOKS_SCAN_MODEL="qwen2.5vl:7b",
        BOOKS_SCAN_API="chat",
    )
    assert (local.model, local.api) == ("qwen2.5vl:7b", "chat")
    assert str(local.client.base_url).startswith("http://localhost:11434/v1")

    # BOOKS_SCAN_BASE_URL / BOOKS_SCAN_API_KEY override a named provider's own.
    moved = reader(
        BOOKS_SCAN_PROVIDER="kie",
        BOOKS_SCAN_BASE_URL="https://api.kie.ai/codex/v1",
        BOOKS_SCAN_API_KEY="other",
        KIE_API_TOKEN="",
    )
    assert str(moved.client.base_url).startswith("https://api.kie.ai/codex/v1")

    # Switching provider is the whole change: each reads its own key.
    openrouter = reader(BOOKS_SCAN_PROVIDER="openrouter", OPENROUTER_API_KEY="r")
    assert str(openrouter.client.base_url).startswith("https://openrouter.ai/api/v1")
    assert openrouter.provider == "OpenRouter"
    ollama = reader(BOOKS_SCAN_PROVIDER="ollama")  # a local server needs no key
    assert str(ollama.client.base_url).startswith("http://localhost:11434/v1")

    with pytest.raises(AgentNotConfiguredError, match="KIE_API_TOKEN"):
        agent_module.front_matter_reader(settings(BOOKS_SCAN_PROVIDER="kie", KIE_API_TOKEN=""))
    with pytest.raises(AgentNotConfiguredError, match="GEMINI_API_KEY is not set"):
        agent_module.front_matter_reader(settings(BOOKS_SCAN_PROVIDER="gemini"))
    with pytest.raises(AgentNotConfiguredError, match="BOOKS_SCAN_BASE_URL"):
        agent_module.front_matter_reader(settings(BOOKS_SCAN_PROVIDER="custom"))


async def test_the_cover_reader_offers_only_the_campus_names_and_asks_for_one_answer() -> None:
    sent: list[dict[str, Any]] = []

    async def create(**body: Any) -> Any:
        sent.append(body)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "title": "Beginner Mathematics",
                    "publisher": None,
                    "version": None,
                    "class_printed": "Grade 2",
                    "class_choice": "Grade 2",
                    "subject_printed": None,
                    "subject_choice": "none",
                    "chapters": [{"number": 1, "title": "Numbers"}],
                }
            ),
            usage=SimpleNamespace(input_tokens=5000, output_tokens=150),
        )

    reader = CompatibleFrontMatterReader(cover_client(responses=create), "gpt-6-luna")
    page = FrontPage(b"jpeg-bytes", "image/jpeg", "")
    reading = await reader.read_front_matter([page], ["Grade 1", "Grade 2"], ["Maths"])

    assert reading.class_choice == "Grade 2"
    (body,) = sent
    assert body["model"] == "gpt-6-luna"
    assert body["stream"] is False
    schema = body["text"]["format"]["schema"]["properties"]
    assert schema["class_choice"]["enum"] == ["Grade 1", "Grade 2", "none"]
    assert schema["subject_choice"]["enum"] == ["Maths", "none"]
    image = body["input"][0]["content"][2]
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    assert reader.usage.calls == {"front_matter": 1}


async def test_a_chat_completions_provider_gets_the_same_request_and_loose_json_is_read() -> None:
    sent: list[dict[str, Any]] = []

    async def create(**body: Any) -> Any:
        sent.append(body)
        # A loosely-following model: a code fence, and fields left out.
        return chat_answer(
            '```json\n{"title": "Beginner Mathematics", "class_choice": "Grade 2"}\n```'
        )

    reader = CompatibleFrontMatterReader(cover_client(chat=create), "qwen2.5vl:7b", "chat")
    page = FrontPage(b"jpeg-bytes", "image/jpeg", "")
    reading = await reader.read_front_matter([page], ["Grade 1", "Grade 2"], [])

    assert (reading.title, reading.class_choice, reading.chapters) == (
        "Beginner Mathematics",
        "Grade 2",
        [],
    )
    (body,) = sent
    assert body["stream"] is False
    system, user = body["messages"]
    assert system["role"] == "system" and "textbook" in system["content"]
    assert user["content"][2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    format_ = body["response_format"]
    assert format_["type"] == "json_schema" and format_["json_schema"]["strict"] is True
    assert format_["json_schema"]["schema"]["properties"]["class_choice"]["enum"] == [
        "Grade 1",
        "Grade 2",
        "none",
    ]
    assert reader.usage.input_tokens == 4000


async def test_a_gateway_error_sent_as_http_200_is_raised_with_its_message() -> None:
    # kie.ai's answer to a model it does not serve on this API.
    async def create(**body: Any) -> Any:
        return SimpleNamespace(
            model_extra={"code": 422, "msg": "The model is not supported", "data": None},
            choices=None,
            usage=None,
        )

    reader = CompatibleFrontMatterReader(cover_client(chat=create), "gpt-6-luna", "chat")
    with pytest.raises(RuntimeError, match="The model is not supported"):
        await reader.read_front_matter([FrontPage(b"x", "image/jpeg", "")], [], [])


async def test_switching_provider_alone_finds_its_api_once_and_remembers_it() -> None:
    calls: list[str] = []

    async def responses(**body: Any) -> Any:
        calls.append("responses")
        raise not_found("responses")  # a Chat-Completions-only provider

    async def chat(**body: Any) -> Any:
        calls.append("chat")
        return chat_answer('{"title": "Beginner Mathematics"}')

    client = cover_client(responses=responses, chat=chat)
    page = FrontPage(b"x", "image/jpeg", "")
    first = await CompatibleFrontMatterReader(client, "gpt-6-luna").read_front_matter(
        [page], [], []
    )
    again = await CompatibleFrontMatterReader(client, "gpt-6-luna").read_front_matter(
        [page], [], []
    )

    assert first.title == again.title == "Beginner Mathematics"
    assert calls == ["responses", "chat", "chat"], "the probe happens once per provider"


async def test_kie_style_not_supported_on_one_api_falls_back_to_the_other() -> None:
    async def responses(**body: Any) -> Any:
        return SimpleNamespace(model_extra={"code": 422, "msg": "The model is not supported"})

    async def chat(**body: Any) -> Any:
        return chat_answer('{"title": "Beginner Mathematics"}')

    reader = CompatibleFrontMatterReader(cover_client(responses=responses, chat=chat), "m")
    reading = await reader.read_front_matter([FrontPage(b"x", "image/jpeg", "")], [], [])
    assert reading.title == "Beginner Mathematics"


async def test_a_real_failure_is_not_retried_on_the_other_api() -> None:
    chat_calls: list[str] = []

    async def responses(**body: Any) -> Any:
        request = httpx2.Request("POST", "http://provider/v1/responses")
        raise AuthenticationError(
            "bad key", response=httpx2.Response(401, request=request), body=None
        )

    async def chat(**body: Any) -> Any:
        chat_calls.append("chat")
        return chat_answer("{}")

    reader = CompatibleFrontMatterReader(cover_client(responses=responses, chat=chat), "m")
    with pytest.raises(AuthenticationError):
        await reader.read_front_matter([FrontPage(b"x", "image/jpeg", "")], [], [])
    assert chat_calls == []


async def test_the_same_model_is_sent_as_each_provider_spells_it() -> None:
    sent: list[str] = []

    async def responses(**body: Any) -> Any:
        sent.append(body["model"])
        return SimpleNamespace(output_text='{"title": "T"}', usage=None)

    page = FrontPage(b"x", "image/jpeg", "")
    openrouter = cover_client(
        models=["anthropic/claude-x", "openai/gpt-6-luna"], responses=responses
    )
    kie_codex = cover_client(models=["gpt-6-1-sol", "gpt-6-luna"], responses=responses)
    unlisted = cover_client(models=["other"], responses=responses)

    await CompatibleFrontMatterReader(openrouter, "gpt-6-luna").read_front_matter([page], [], [])
    await CompatibleFrontMatterReader(kie_codex, "gpt-6.1-sol").read_front_matter([page], [], [])
    await CompatibleFrontMatterReader(unlisted, "gpt-6-luna").read_front_matter([page], [], [])

    assert sent == ["openai/gpt-6-luna", "gpt-6-1-sol", "gpt-6-luna"]


async def test_the_check_says_whether_the_key_and_model_will_work() -> None:
    def failing(error: type[APIStatusError], status: int) -> Any:
        def listing() -> Any:
            request = httpx2.Request("GET", "http://provider/v1/models")
            raise error("no", response=httpx2.Response(status, request=request), body=None)

        client = cover_client()
        client.models = SimpleNamespace(list=listing)
        return client

    rejected = CompatibleFrontMatterReader(
        failing(AuthenticationError, 401), "m", provider="kie.ai"
    )
    assert await rejected.check() == "kie.ai rejected the API key."

    listed = cover_client(models=["openai/gpt-6-luna"])
    assert await CompatibleFrontMatterReader(listed, "gpt-6-luna").check() is None

    elsewhere = cover_client(models=["llama-4-scout"])
    assert (
        await CompatibleFrontMatterReader(elsewhere, "gpt-6-luna", provider="Groq").check()
        == "Groq does not offer the model gpt-6-luna."
    )

    # A provider without a model list is given the benefit of the doubt.
    unlisted = CompatibleFrontMatterReader(failing(NotFoundError, 404), "gpt-6-luna")
    assert await unlisted.check() is None


async def test_the_check_is_remembered_rather_than_asked_every_time() -> None:
    asked: list[str] = []

    async def listing() -> AsyncIterator[Any]:
        asked.append("models")
        yield SimpleNamespace(id="gpt-6-luna")

    client = cover_client()
    client.models = SimpleNamespace(list=listing)
    for _ in range(3):
        assert await CompatibleFrontMatterReader(client, "gpt-6-luna").check() is None
    assert asked == ["models"]
