"""The model boundary.

Deliberately incapable: instruction, untrusted data, schema, text back. No
tools, no function calling, no session (md/09 §6.2, locked decision B4) — the
signature enforces it, since there is nowhere to pass a tool.

`VertexProvider` is unverified: no credentials exist here, so it has never made
a real call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from cairn_api.pipeline.credentials import ApplicationDefaultCredentials, TokenSource

#: A scripted reply: fixed text, or a function of the request.
_Responder = str | Callable[["ModelRequest"], str]


class ModelError(RuntimeError):
    """The provider could not produce a usable response."""


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One call to a model.

    Instruction and data are separate fields: concatenating them is how
    indirect prompt injection works (md/09 §6.1). No field to merge them into.
    """

    #: Trusted. Written by us, never derived from ingested content.
    instruction: str

    #: Untrusted. Commit messages, chat, transcripts — anything a person wrote.
    untrusted_data: str

    response_schema: dict[str, Any] | None = None

    #: Not configurable per call: extraction is transcription, not creation.
    temperature: float = 0.0

    max_output_tokens: int = 2048


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str

    #: For cost attribution (md/10 §7).
    input_tokens: int = 0
    output_tokens: int = 0

    model: str = "unknown"


class ModelProvider(Protocol):
    """One method — every widening of this interface widens what an injected
    instruction can reach."""

    async def complete(self, request: ModelRequest) -> ModelResponse: ...


@dataclass
class ScriptedProvider:
    """A deterministic provider, driven by a rule table.

    Not a mock: it responds rather than asserting on how it was called, so
    the pipeline around it is exercised end to end.
    """

    #: Matched in order; the first hit responds.
    rules: list[tuple[Callable[[ModelRequest], bool], _Responder]] = field(default_factory=list)

    #: Used when nothing matches.
    default: str = "{}"

    #: Every request seen, so a test can assert on prompt structure.
    calls: list[ModelRequest] = field(default_factory=list)

    model_name: str = "scripted"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        for matches, response in self.rules:
            if matches(request):
                text = response(request) if callable(response) else response
                return ModelResponse(text=text, model=self.model_name)
        return ModelResponse(text=self.default, model=self.model_name)

    def when(
        self,
        predicate: Callable[[ModelRequest], bool],
        respond: str | dict[str, Any] | Callable[[ModelRequest], str],
    ) -> ScriptedProvider:
        payload: _Responder = (
            respond if callable(respond) or isinstance(respond, str) else json.dumps(respond)
        )
        self.rules.append((predicate, payload))
        return self


def contains(needle: str) -> Callable[[ModelRequest], bool]:
    def predicate(request: ModelRequest) -> bool:
        return needle.lower() in request.untrusted_data.lower()

    return predicate


def instructed(needle: str) -> Callable[[ModelRequest], bool]:
    """Matches the instruction rather than the data, so one provider can
    play several stages in a test."""

    def predicate(request: ModelRequest) -> bool:
        return needle.lower() in request.instruction.lower()

    return predicate


class VertexProvider:
    """Google Vertex AI over REST (md/06).

    REST rather than `google-cloud-aiplatform`: the SDK is a large synchronous
    dependency needing thread offloading, and `httpx` is already here and async.
    """

    #: Bounded, not unbounded: synthesis runs on a worker and would hold the slot.
    TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        *,
        project_id: str,
        location: str = "us-central1",
        model: str = "gemini-2.0-flash",
        token_source: TokenSource | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not project_id:
            # Empty project id would otherwise yield a URL that 404s opaquely.
            msg = "VertexProvider requires a GCP project id"
            raise ValueError(msg)
        self._project = project_id
        self._location = location
        self._model = model
        self._tokens = token_source or ApplicationDefaultCredentials()
        self._client = client
        self._owns_client = client is None

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self._location}-aiplatform.googleapis.com/v1"
            f"/projects/{self._project}/locations/{self._location}"
            f"/publishers/google/models/{self._model}:generateContent"
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        payload = self._payload(request)
        token = await self._tokens.token()

        client = self._client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        try:
            response = await client.post(
                self.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            # Wrapped so stages catching `ModelError` don't need to know the HTTP client.
            msg = f"Vertex request failed: {exc}"
            raise ModelError(msg) from exc
        finally:
            if self._owns_client:
                await client.aclose()

        if response.status_code != httpx.codes.OK:
            # Body included: Vertex explains refusals there (quota, safety, bad model name).
            msg = f"Vertex returned {response.status_code}: {response.text[:500]}"
            raise ModelError(msg)

        return self._parse(response.json())

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        """Request body. Instruction and untrusted data stay in separate parts:
        concatenating them undoes the injection defence (md/09 §6.1).
        """
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.instruction}, {"text": request.untrusted_data}],
                }
            ],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
                # Requested at the API level too, not just in the prompt.
                "responseMimeType": "application/json",
            },
        }
        if request.response_schema is not None:
            payload["generationConfig"]["responseSchema"] = request.response_schema
        return payload

    def _parse(self, body: dict[str, Any]) -> ModelResponse:
        """Turn a Vertex response into text and accounting.

        A blocked or empty response returns empty text rather than raising:
        raising would dead-letter a job over content the model rightly refused.
        """
        candidates = body.get("candidates") or []
        text = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))

        usage = body.get("usageMetadata") or {}
        return ModelResponse(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
            model=self._model,
        )
