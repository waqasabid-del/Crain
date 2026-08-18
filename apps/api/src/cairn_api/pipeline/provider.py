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
from typing import Any, ClassVar, Protocol

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


class OpenAIProvider:
    """OpenAI chat completions over REST.

    `httpx` rather than the `openai` SDK, for the reason `VertexProvider` gives:
    the client is already here and async, and one HTTP shape is easier to reason
    about than two SDK lifecycles.

    **Instruction and untrusted data go as two messages and are never joined.**
    `ModelRequest` keeps them apart because concatenating them is how indirect
    prompt injection works (md/09 §6.1); this adapter is the last place that
    separation could be quietly undone, since nothing downstream can see what
    was actually sent. The system message is ours; the user message is whatever a
    stranger wrote, delimiters intact.
    """

    #: Bounded, matching Vertex: synthesis runs on a worker and would hold the
    #: slot open indefinitely otherwise.
    TIMEOUT_SECONDS: ClassVar[float] = 120.0

    ENDPOINT: ClassVar[str] = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            # An empty key yields a 401 per call rather than one clear failure,
            # so it is refused here as well as at boot in `config.py`.
            msg = "OpenAIProvider requires an API key"
            raise ValueError(msg)
        self._api_key = api_key
        self._model = model
        self._client = client
        self._owns_client = client is None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        client = self._client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        try:
            response = await client.post(
                self.ENDPOINT,
                json=self._payload(request),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            # Named separately from other transport errors: a timeout is the one
            # an operator retries rather than investigates.
            msg = "OpenAI request timed out"
            raise ModelError(msg) from exc
        except httpx.HTTPError as exc:
            # `exc` carries the URL and the failure class, never a body.
            msg = f"OpenAI request failed: {type(exc).__name__}"
            raise ModelError(msg) from exc
        finally:
            if self._owns_client:
                await client.aclose()

        self._raise_for_status(response)
        return self._parse(response)

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        """The request body. **Two messages, never one.**

        There is no branch here that merges `instruction` and `untrusted_data`,
        and no field on `ModelRequest` that would let a caller ask for one.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.instruction},
                {"role": "user", "content": request.untrusted_data},
            ],
            # Not read from the request: extraction is transcription, not
            # creation, and a per-call temperature would make one workspace's
            # facts less reproducible than another's.
            "temperature": 0.0,
            "max_tokens": request.max_output_tokens,
        }
        if request.response_schema is not None:
            # Enforced by the API rather than requested in the prompt. `strict`
            # is the difference between a schema the model is encouraged to
            # follow and one it cannot violate — the same guarantee Vertex gives
            # through `responseSchema`.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "cairn_extraction",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Turn a non-200 into a `ModelError` that carries no customer content.

        **Deliberately unlike `VertexProvider`, which includes its response
        body.** Vertex explains refusals there and the explanation is worth
        having; OpenAI's error body adds nothing a status code does not, and it
        can echo the prompt — which is a customer's words, on their way to a log
        store that sits outside the erasure path.
        """
        if response.status_code == httpx.codes.OK:
            return

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            retry_after = response.headers.get("Retry-After")
            # The number is the only part of a 429 worth keeping: it tells the
            # worker when to come back and it identifies nobody.
            msg = (
                f"OpenAI rate limited the request; retry after {retry_after}s"
                if retry_after
                else "OpenAI rate limited the request"
            )
            raise ModelError(msg)

        msg = f"OpenAI returned {response.status_code}"
        raise ModelError(msg)

    def _parse(self, response: httpx.Response) -> ModelResponse:
        """Read the completion, and refuse anything that only looks like one."""
        try:
            body = response.json()
        except ValueError as exc:
            msg = "OpenAI returned a body that is not JSON"
            raise ModelError(msg) from exc

        choices = body.get("choices") or []
        if not choices:
            # **Not empty text.** Vertex returns empty text for a blocked
            # response because a safety refusal is a legitimate answer; an
            # OpenAI response with no choices is a shape nothing should produce,
            # and reading it as empty would file "the model returned nothing" as
            # "there was nothing to find".
            msg = "OpenAI returned no choices"
            raise ModelError(msg)

        message = choices[0].get("message") or {}
        text = message.get("content") or ""

        usage = body.get("usage")
        if not isinstance(usage, dict) or "prompt_tokens" not in usage:
            # A silently-zero token count would add nothing to the ledger, so
            # the token ceiling would never be reached and the call-count
            # ceiling — a backstop — would become the only control.
            msg = "OpenAI response carried no usage; refusing to record zero cost"
            raise ModelError(msg)

        return ModelResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            model=str(body.get("model") or self._model),
        )
