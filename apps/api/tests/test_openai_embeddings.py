"""OpenAI embeddings at exactly 768 dimensions, against a mocked transport.

**Width is not a preference here, it is the schema.** `fact_embeddings.embedding`
is `Vector(768)`; a vector of any other width cannot be stored, and — worse — a
mixed-width table cannot be searched, because similarity between vectors of
different lengths is undefined. So the interesting tests are the refusals.

The model-name string is load-bearing for the same reason. Vectors are only ever
searched under the name they were written with, so a rename does not migrate
anything: it silently partitions the table into rows nothing will ever match
again, with no error and no empty-result signal that looks like a defect.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cairn_api.pipeline.embeddings import (
    DIMENSIONS,
    EmbeddingError,
    OpenAIEmbeddingProvider,
)

pytestmark = pytest.mark.integration


def _vector(width: int = DIMENSIONS) -> list[float]:
    return [0.01] * width


def _body(*widths: int) -> dict[str, Any]:
    return {
        "model": "text-embedding-3-small",
        "data": [{"index": i, "embedding": _vector(w)} for i, w in enumerate(widths)],
        "usage": {"prompt_tokens": 8, "total_tokens": 8},
    }


def _provider(transport: httpx.MockTransport) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        api_key="sk-test-not-a-real-key",
        client=httpx.AsyncClient(transport=transport),
    )


class TestTheModelNameIsPartOfTheData:
    def test_the_name_is_exactly_this_string(self) -> None:
        """**Asserted literally, on purpose.**

        This value is written beside every vector and used as the equality
        predicate when retrieval searches. Changing it does not migrate
        anything — it partitions the table, and the symptom is a workspace whose
        retrieval quietly returns nothing while every layer reports success. The
        dimension is in the name so that a future 1536-wide variant cannot
        occupy the same partition.
        """
        assert OpenAIEmbeddingProvider.MODEL_NAME == "openai-te3s-768"

    def test_the_provider_reports_the_schema_width(self) -> None:
        assert _provider(httpx.MockTransport(lambda r: httpx.Response(200))).dimensions == 768
        assert DIMENSIONS == 768


class TestItAsksForTheRightShape:
    async def test_it_requests_native_768_rather_than_truncating(self) -> None:
        """OpenAI shortens server-side; truncating a 1536-wide vector locally
        would produce something that is not a unit vector and not comparable to
        anything else in the column."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.content))
            return httpx.Response(200, json=_body(DIMENSIONS))

        await _provider(httpx.MockTransport(handler)).embed(["one"])

        assert captured["model"] == "text-embedding-3-small"
        assert captured["dimensions"] == 768
        assert captured["input"] == ["one"]

    async def test_a_correct_batch_comes_back_intact(self) -> None:
        vectors = await _provider(
            httpx.MockTransport(lambda r: httpx.Response(200, json=_body(*[DIMENSIONS] * 3)))
        ).embed(["a", "b", "c"])

        assert len(vectors) == 3
        assert all(len(vector) == DIMENSIONS for vector in vectors)

    async def test_no_texts_makes_no_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("embedding an empty list should not call the API")

        assert await _provider(httpx.MockTransport(handler)).embed([]) == []


class TestAWrongWidthIsRefused:
    @pytest.mark.parametrize("width", [1536, 767, 769, 0])
    async def test_the_batch_is_refused_rather_than_stored(self, width: int) -> None:
        """**A wrong-width write must be impossible, not merely unlikely.**

        The column is fixed-width, so a short vector fails at insert — but a
        1536-wide one from a misconfigured `dimensions` parameter would fail
        deep in the driver, mid-transaction, after the batch was already
        assembled. Refusing here names the cause.
        """
        with pytest.raises(EmbeddingError, match="768"):
            await _provider(
                httpx.MockTransport(lambda r: httpx.Response(200, json=_body(width)))
            ).embed(["one"])

    async def test_one_bad_vector_refuses_the_whole_batch(self) -> None:
        """Partial acceptance would attach every vector after the gap to the
        wrong fact — silently, since the counts would still look plausible."""
        with pytest.raises(EmbeddingError):
            await _provider(
                httpx.MockTransport(
                    lambda r: httpx.Response(200, json=_body(DIMENSIONS, 1536, DIMENSIONS))
                )
            ).embed(["a", "b", "c"])

    async def test_a_short_count_is_refused(self) -> None:
        """Fewer vectors than texts misaligns the pairing for everything after
        the missing one."""
        with pytest.raises(EmbeddingError, match="2 embeddings for 3"):
            await _provider(
                httpx.MockTransport(lambda r: httpx.Response(200, json=_body(*[DIMENSIONS] * 2)))
            ).embed(["a", "b", "c"])


class TestBatching:
    async def test_it_splits_at_the_batch_size(self) -> None:
        """One call per fact would multiply latency and per-request cost by the
        size of the workspace."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            inputs = json.loads(request.content)["input"]
            calls.append(len(inputs))
            return httpx.Response(200, json=_body(*[DIMENSIONS] * len(inputs)))

        size = OpenAIEmbeddingProvider.BATCH_SIZE
        vectors = await _provider(httpx.MockTransport(handler)).embed(["x"] * (size + 3))

        assert calls == [size, 3]
        assert len(vectors) == size + 3


class TestFailuresBecomeEmbeddingError:
    async def test_a_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(EmbeddingError, match="timed out"):
            await _provider(httpx.MockTransport(handler)).embed(["one"])

    async def test_rate_limiting_surfaces_retry_after(self) -> None:
        transport = httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"Retry-After": "12"}, json={})
        )

        with pytest.raises(EmbeddingError, match="12"):
            await _provider(transport).embed(["one"])

    async def test_a_server_error(self) -> None:
        with pytest.raises(EmbeddingError, match="500"):
            await _provider(httpx.MockTransport(lambda r: httpx.Response(500, json={}))).embed(
                ["one"]
            )

    async def test_no_body_reaches_the_error(self) -> None:
        """Embedding input is the fact's own text — a customer's words."""
        private = "the customer wrote something private"
        transport = httpx.MockTransport(
            lambda r: httpx.Response(500, json={"error": {"message": private}})
        )

        with pytest.raises(EmbeddingError) as caught:
            await _provider(transport).embed([private])

        assert private not in str(caught.value)


class TestTheFactoryReachesIt:
    def test_the_openai_backend_selects_this_embedder(self) -> None:
        from cairn_api.config import Settings
        from cairn_api.pipeline import jobs
        from pydantic import SecretStr

        providers = jobs.select_providers(
            Settings(
                environment="local",
                model_backend="openai",
                openai_api_key=SecretStr("sk-test-not-a-real-key"),
            )
        )

        assert isinstance(providers.embedder, OpenAIEmbeddingProvider)
        assert providers.embedder.dimensions == DIMENSIONS


class TestTheStoredNameMatchesTheEmbedderThatWroteIt:
    """The bug this class exists to prevent is silent and unrecoverable.

    Vectors are written with a `model_name` and searched under it. If the
    selected embedder and the recorded name disagree, OpenAI vectors land in the
    `hashing-v1` partition beside hashing vectors — two incomparable geometries
    under one label. Nothing errors. Retrieval simply returns nonsense
    neighbours, and the only fix afterwards is to re-embed everything, because
    the rows cannot be told apart.
    """

    def test_every_embedder_reports_its_own_name(self) -> None:
        from cairn_api.pipeline.embeddings import (
            DEFAULT_EMBEDDING_MODEL,
            HashingEmbedder,
            VertexEmbeddingProvider,
        )

        assert HashingEmbedder().model_name == DEFAULT_EMBEDDING_MODEL
        assert OpenAIEmbeddingProvider(api_key="sk-x").model_name == "openai-te3s-768"
        # Vertex reports its own too. It was previously stored under the hashing
        # name, which is the same defect one provider earlier.
        assert VertexEmbeddingProvider(project_id="p").model_name == "vertex-te005-768"

    def test_the_handler_records_the_name_the_embedder_reports(self) -> None:
        """`make_handler` defaulted to the hashing name regardless of which
        embedder it was given, so selecting a real one silently mislabelled
        every vector it wrote."""
        import inspect

        from cairn_api.pipeline import jobs

        source = inspect.getsource(jobs.make_handler)

        assert "DEFAULT_EMBEDDING_MODEL" not in source
        assert "model_name" in source
