"""Embeddings — the entry point into the graph, and nothing more.

Vector search finds a door; the graph walks the building (md/09 §3.1):
similarity retrieves passages that merely sound related and cannot traverse
a chain, so this module just turns a statement into a vector for
`retrieval.py` to start from.

What gets embedded is the extracted fact, not the raw event — contextual
retrieval cuts retrieval failures by about half (md/09 §4.4).

`DIMENSIONS` is checked against pgvector's HNSW ceiling of 2,000 (md/06 §4.4)
here, before model selection, rather than discovered via a failing migration.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import ClassVar, Protocol

import httpx

from cairn_api.pipeline.credentials import ApplicationDefaultCredentials, TokenSource

#: pgvector's hard limit for HNSW indexing (md/06 §4.4).
HNSW_DIMENSION_LIMIT = 2000

#: 768 rather than 1536: memory, not quality — halving the width roughly
#: doubles what fits in cache. Changing this needs a migration and re-embed.
DIMENSIONS = 768

if DIMENSIONS > HNSW_DIMENSION_LIMIT:  # pragma: no cover - a compile-time guard
    msg = (
        f"DIMENSIONS={DIMENSIONS} exceeds pgvector's HNSW limit of "
        f"{HNSW_DIMENSION_LIMIT} (md/06 §4.4). The index cannot be created."
    )
    raise ValueError(msg)


#: One definition: `graph.build` and `retrieve` disagreeing fails silently
#: (empty results, nothing logged).
DEFAULT_EMBEDDING_MODEL = "hashing-v1"


class EmbeddingError(RuntimeError):
    """The provider could not produce a usable vector."""


class EmbeddingProvider(Protocol):
    """Batched rather than one at a time: embedding is charged per call, not just per token."""

    @property
    def dimensions(self) -> int: ...

    #: The name every vector this provider writes is stored under, and the
    #: equality predicate retrieval searches with. On the protocol rather than
    #: chosen by the caller, because a caller that picks the wrong one writes
    #: incomparable geometries into a single partition and nothing errors.
    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


_WORD = re.compile(r"[a-z0-9][a-z0-9'#/_.-]*")


class HashingEmbedder:
    """A deterministic embedder with no model behind it.

    Not a mock: real feature hashing, weak only at meaning ("shipped the
    rate limiter" vs "deployed throttling" land far apart) — which is why
    it's safe for tests. Also a working fallback with no credentials.
    """

    @property
    def model_name(self) -> str:
        return DEFAULT_EMBEDDING_MODEL

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        if dimensions < 1:
            msg = "dimensions must be positive"
            raise ValueError(msg)
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        words = _WORD.findall(text.lower())
        # Bigrams too, so "not blocked" and "blocked" don't land in the same place.
        features = words + [f"{a}~{b}" for a, b in itertools.pairwise(words)]

        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            # Sign from a different byte of the same digest, so collisions cancel
            # rather than accumulate into one dominant direction.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Pure punctuation: zeros, not a raise. Cosine distance to a zero
            # vector is undefined, so it matches nothing — the honest result.
            return vector
        return [value / norm for value in vector]


class VertexEmbeddingProvider:
    """Google Vertex AI text embeddings, over the REST API.

    Implemented, not verified — same standing as `VertexProvider`.
    `text-embedding-005` outputs 768 dimensions natively, hence `DIMENSIONS`.
    """

    #: Vertex accepts up to 250 instances; 100 leaves headroom for payload size.
    BATCH_SIZE = 100

    TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        *,
        project_id: str,
        location: str = "us-central1",
        model: str = "text-embedding-005",
        token_source: TokenSource | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not project_id:
            msg = "VertexEmbeddingProvider requires a GCP project id"
            raise ValueError(msg)
        self._project = project_id
        self._location = location
        self._model = model
        self._tokens = token_source or ApplicationDefaultCredentials()
        self._client = client
        self._owns_client = client is None

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    @property
    def model_name(self) -> str:
        """Its own name, not the hashing one.

        Vertex vectors were previously written under `hashing-v1` — the handler's
        default — which put two incomparable geometries in one partition. The
        width is in the name for the same reason it is in OpenAI's.
        """
        return "vertex-te005-768"

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self._location}-aiplatform.googleapis.com/v1"
            f"/projects/{self._project}/locations/{self._location}"
            f"/publishers/google/models/{self._model}:predict"
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        client = self._client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        vectors: list[list[float]] = []
        try:
            for index in range(0, len(texts), self.BATCH_SIZE):
                batch = texts[index : index + self.BATCH_SIZE]
                vectors.extend(await self._embed_batch(client, batch))
        finally:
            if self._owns_client:
                await client.aclose()

        if len(vectors) != len(texts):
            # A count mismatch silently misattaches every vector after the gap.
            msg = f"Vertex returned {len(vectors)} embeddings for {len(texts)} texts"
            raise EmbeddingError(msg)
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        token = await self._tokens.token()
        payload = {
            "instances": [{"content": text} for text in batch],
            "parameters": {"outputDimensionality": DIMENSIONS},
        }

        try:
            response = await client.post(
                self.endpoint, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            msg = f"Vertex embedding request failed: {exc}"
            raise EmbeddingError(msg) from exc

        if response.status_code != httpx.codes.OK:
            msg = f"Vertex embeddings returned {response.status_code}: {response.text[:500]}"
            raise EmbeddingError(msg)

        predictions = response.json().get("predictions") or []
        vectors: list[list[float]] = []
        for prediction in predictions:
            values = ((prediction or {}).get("embeddings") or {}).get("values")
            if not isinstance(values, list) or len(values) != DIMENSIONS:
                # Fixed-width column: vectors of different widths are not comparable.
                msg = (
                    f"Vertex returned a vector of width "
                    f"{len(values) if isinstance(values, list) else 'unknown'}, "
                    f"expected {DIMENSIONS}"
                )
                raise EmbeddingError(msg)
            vectors.append([float(value) for value in values])
        return vectors


class OpenAIEmbeddingProvider:
    """OpenAI text embeddings, shortened natively to 768 dimensions.

    **768 is the schema, not a preference.** `fact_embeddings.embedding` is
    `Vector(768)`, and similarity between vectors of different widths is
    undefined — so a mixed-width column is not a degraded index, it is an
    unsearchable one. `text-embedding-3-small` is 1536 natively and supports
    server-side shortening, which is what the `dimensions` parameter asks for.
    Truncating locally would be worse than wrong: the result is no longer a unit
    vector, so its cosine distance to everything already stored is meaningless
    while remaining perfectly computable.
    """

    #: **Written beside every vector, and the equality predicate retrieval
    #: searches under.** Renaming this does not migrate anything: it partitions
    #: the table into rows nothing will ever match again, and the symptom is a
    #: workspace whose retrieval quietly returns nothing while every layer
    #: reports success. The width is in the name so a future 1536-wide variant
    #: cannot occupy the same partition.
    MODEL_NAME: ClassVar[str] = "openai-te3s-768"

    MODEL: ClassVar[str] = "text-embedding-3-small"

    ENDPOINT: ClassVar[str] = "https://api.openai.com/v1/embeddings"

    #: OpenAI accepts up to 2,048 inputs per request. 100 leaves headroom for
    #: payload size, and matches the Vertex adapter so one number describes the
    #: pipeline's batching rather than two.
    BATCH_SIZE: ClassVar[int] = 100

    TIMEOUT_SECONDS: ClassVar[float] = 60.0

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            msg = "OpenAIEmbeddingProvider requires an API key"
            raise ValueError(msg)
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    @property
    def model_name(self) -> str:
        return self.MODEL_NAME

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            # No call: an empty request still costs a round trip and, on some
            # plans, a minimum charge.
            return []

        client = self._client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        vectors: list[list[float]] = []
        try:
            for index in range(0, len(texts), self.BATCH_SIZE):
                vectors.extend(
                    await self._embed_batch(client, texts[index : index + self.BATCH_SIZE])
                )
        finally:
            if self._owns_client:
                await client.aclose()

        if len(vectors) != len(texts):
            # A count mismatch misattaches every vector after the gap, and the
            # numbers stay plausible enough that nothing downstream notices.
            msg = f"OpenAI returned {len(vectors)} embeddings for {len(texts)} texts"
            raise EmbeddingError(msg)
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        payload = {
            "model": self.MODEL,
            "input": batch,
            # Server-side shortening. See the class docstring for why this is
            # not done locally.
            "dimensions": DIMENSIONS,
        }

        try:
            response = await client.post(
                self.ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            msg = "OpenAI embedding request timed out"
            raise EmbeddingError(msg) from exc
        except httpx.HTTPError as exc:
            msg = f"OpenAI embedding request failed: {type(exc).__name__}"
            raise EmbeddingError(msg) from exc

        if response.status_code != httpx.codes.OK:
            # No body, for the reason the chat provider gives: the input here is
            # the fact's own text, so an echoed error carries a customer's words
            # into a log store outside the erasure path.
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                retry_after = response.headers.get("Retry-After")
                msg = (
                    f"OpenAI rate limited the embedding request; retry after {retry_after}s"
                    if retry_after
                    else "OpenAI rate limited the embedding request"
                )
                raise EmbeddingError(msg)
            msg = f"OpenAI embeddings returned {response.status_code}"
            raise EmbeddingError(msg)

        try:
            body = response.json()
        except ValueError as exc:
            msg = "OpenAI embeddings returned a body that is not JSON"
            raise EmbeddingError(msg) from exc

        vectors: list[list[float]] = []
        for item in body.get("data") or []:
            values = (item or {}).get("embedding")
            if not isinstance(values, list) or len(values) != DIMENSIONS:
                # **The whole batch is refused, not the row.** Accepting the
                # good ones would attach every vector after the gap to the wrong
                # fact, which is a silent mis-association rather than a failure.
                width = len(values) if isinstance(values, list) else "unknown"
                msg = f"OpenAI returned a vector of width {width}, expected {DIMENSIONS}"
                raise EmbeddingError(msg)
            vectors.append([float(value) for value in values])
        return vectors
