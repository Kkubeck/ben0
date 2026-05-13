"""Local embedding helpers for BEN-0 retrieval."""

from __future__ import annotations

from pathlib import Path


class EmbeddingModel:
    """Wrapper around fastembed for local text embeddings."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: Path | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised in integration environments
            raise ImportError(
                "Vector search dependencies are not installed. Install with `pip install ben0[vectors]`."
            ) from exc

        self.model_name = model_name
        self.cache_dir = cache_dir
        kwargs: dict[str, str] = {"model_name": model_name}
        if cache_dir is not None:
            kwargs["cache_dir"] = str(cache_dir)
        self._model = TextEmbedding(**kwargs)
        probe = self.embed_texts(["dimension probe"])
        self._dimension = len(probe[0]) if probe else 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        if not texts:
            return []
        return [self._coerce_vector(vector) for vector in self._model.embed(texts)]

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query text."""
        if hasattr(self._model, "query_embed"):
            vectors = list(self._model.query_embed([query]))
        else:
            vectors = list(self._model.embed([query]))
        if not vectors:
            return []
        return self._coerce_vector(vectors[0])

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @staticmethod
    def _coerce_vector(vector: object) -> list[float]:
        if hasattr(vector, "tolist"):
            values = vector.tolist()
        else:
            values = list(vector)  # type: ignore[arg-type]
        return [float(value) for value in values]
