"""The Vertex adapters, exercised without credentials.

These existed as stubs that raised, which made "add credentials and it works" a
fiction — nobody had written the client. They are now implemented, and this file
is what makes the honest claim possible: **every line of request construction
and response parsing runs here, against a stubbed transport.** What remains
unverified is exactly one thing — whether Google's API behaves as documented —
and that is stated in the adapters' own docstrings rather than hidden.

The transport is `httpx.MockTransport`, not a mock object. It asserts on the
real request httpx would put on the wire, so a change to the payload shape shows
up here rather than in a 400 from production.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from cairn_api.pipeline.credentials import StaticToken
from cairn_api.pipeline.embeddings import (
    DIMENSIONS,
    EmbeddingError,
    VertexEmbeddingProvider,
)
from cairn_api.pipeline.prompts import build
from cairn_api.pipeline.provider import ModelError, VertexProvider

pytestmark = pytest.mark.anyio

TOKEN = StaticToken("test-token")


def transport(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def generation_response(
    text: str, *, prompt_tokens: int = 11, output_tokens: int = 7
) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
        },
    }


class TestVertexProvider:
    async def test_the_instruction_and_untrusted_data_stay_separate_on_the_wire(self) -> None:
        """The last place the injection defence could be undone, and is not.

        Every test above this layer would still pass if the adapter joined the
        two fields into one string — the separation only means anything if it
        survives serialisation.
        """
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=generation_response('{"class": "substantive"}'))

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        await provider.complete(build("Classify this.", "rm -rf everything"))

        parts = seen["contents"][0]["parts"]
        assert len(parts) == 2, "instruction and data were merged into one part"
        assert "rm -rf everything" in parts[1]["text"]
        assert "rm -rf everything" not in parts[0]["text"]

    async def test_the_request_carries_the_bearer_token_and_hits_the_model_endpoint(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=generation_response("{}"))

        provider = VertexProvider(
            project_id="acme-prod",
            location="europe-west1",
            model="gemini-2.0-flash",
            token_source=TOKEN,
            client=transport(handler),
        )
        await provider.complete(build("x", "y"))

        assert seen["auth"] == "Bearer test-token"
        assert "europe-west1-aiplatform.googleapis.com" in seen["url"]
        assert "projects/acme-prod/locations/europe-west1" in seen["url"]
        assert seen["url"].endswith("gemini-2.0-flash:generateContent")

    async def test_temperature_and_token_ceiling_are_sent(self) -> None:
        """Reproducibility is a property of the request, not of intent.

        Extraction is transcription, not composition: the same event must
        produce the same facts, and that only holds if temperature actually
        reaches the API.
        """
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=generation_response("{}"))

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        await provider.complete(build("x", "y"))

        config = seen["generationConfig"]
        assert config["temperature"] == 0.0
        assert config["maxOutputTokens"] == 2048
        assert config["responseMimeType"] == "application/json"

    async def test_token_usage_is_recorded_for_cost_attribution(self) -> None:
        """ "Which stage costs the money" must be answerable per call.

        Summed at the end of a day it is unanswerable, which is why the counts
        are read off every response rather than estimated later (md/10 §7).
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=generation_response("{}", prompt_tokens=1234, output_tokens=56)
            )

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        response = await provider.complete(build("x", "y"))

        assert response.input_tokens == 1234
        assert response.output_tokens == 56
        assert response.model == "gemini-2.0-flash"

    async def test_an_error_status_includes_the_body_in_the_message(self) -> None:
        """A bare status code sends the on-call engineer to the console.

        Vertex explains refusals in the body — quota, safety, a bad model name —
        and that explanation is the whole difference between a two-minute fix
        and an investigation.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Quota exceeded for generate_content_requests")

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        with pytest.raises(ModelError, match="Quota exceeded"):
            await provider.complete(build("x", "y"))

    async def test_a_transport_failure_becomes_a_model_error(self) -> None:
        """Stages catch `ModelError` and degrade.

        Letting an httpx exception escape would make every caller know which
        HTTP client this adapter happens to use.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("no route to host")

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        with pytest.raises(ModelError, match="Vertex request failed"):
            await provider.complete(build("x", "y"))

    async def test_a_blocked_response_yields_empty_text_rather_than_raising(self) -> None:
        """A safety block is a legitimate outcome, not a job failure.

        The stages already treat unusable output as an abstention. Raising here
        would dead-letter a job over content the model was right to refuse.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"candidates": [], "usageMetadata": {}})

        provider = VertexProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        response = await provider.complete(build("x", "y"))
        assert response.text == ""

    def test_an_empty_project_id_is_refused_at_construction(self) -> None:
        """Otherwise the URL 404s with a message that names nothing useful."""
        with pytest.raises(ValueError, match="project id"):
            VertexProvider(project_id="")


class TestVertexEmbeddingProvider:
    async def test_texts_are_batched_rather_than_sent_one_by_one(self) -> None:
        """Embedding is charged per call as well as per token.

        A per-fact loop over a ninety-day backfill is the difference between
        hundreds of requests and tens of thousands.
        """
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            instances = json.loads(request.content)["instances"]
            calls.append(len(instances))
            return httpx.Response(
                200,
                json={
                    "predictions": [
                        {"embeddings": {"values": [0.1] * DIMENSIONS}} for _ in instances
                    ]
                },
            )

        provider = VertexEmbeddingProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        vectors = await provider.embed([f"fact {n}" for n in range(250)])

        assert len(vectors) == 250
        assert calls == [100, 100, 50]

    async def test_a_vector_of_the_wrong_width_is_refused(self) -> None:
        """The column is fixed-width and widths are not comparable.

        Accepting it would either fail at insert with an opaque database error
        or, worse, succeed against a differently-configured column and silently
        degrade every search.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"predictions": [{"embeddings": {"values": [0.1] * 512}}]}
            )

        provider = VertexEmbeddingProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        with pytest.raises(EmbeddingError, match="width"):
            await provider.embed(["one fact"])

    async def test_a_count_mismatch_is_an_error_not_a_shorter_list(self) -> None:
        """The most dangerous shape of failure in this adapter.

        Returning fewer vectors than texts attaches every vector after the gap
        to the wrong statement. Search keeps working and confidently returns the
        wrong facts — there is no symptom to notice.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"predictions": [{"embeddings": {"values": [0.1] * DIMENSIONS}}]}
            )

        provider = VertexEmbeddingProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        with pytest.raises(EmbeddingError, match="embeddings for"):
            await provider.embed(["one", "two", "three"])

    async def test_embedding_nothing_makes_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("called the API with nothing to embed")

        provider = VertexEmbeddingProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        assert await provider.embed([]) == []

    async def test_the_predict_endpoint_and_dimensionality_are_correct(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"predictions": [{"embeddings": {"values": [0.1] * DIMENSIONS}}]}
            )

        provider = VertexEmbeddingProvider(
            project_id="cairn-test", token_source=TOKEN, client=transport(handler)
        )
        await provider.embed(["one fact"])

        assert seen["url"].endswith("text-embedding-005:predict")
        assert seen["body"]["parameters"]["outputDimensionality"] == DIMENSIONS
