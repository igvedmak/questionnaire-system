"""Lazy-loaded sentence-transformer embeddings for free-text answers.

The ``sentence-transformers`` dependency is in the ``analytics`` extra so
that the core install stays small. ``embed_text`` raises a clear error if
the extra wasn't installed.

Model: ``all-MiniLM-L6-v2`` — 384-dim, ~80MB, CPU-fine. We embed answers
synchronously on submit in this round; promotion to a background worker
is the documented next step.
"""

from __future__ import annotations

import struct
from functools import lru_cache


_DIM = 384  # all-MiniLM-L6-v2 embedding size


class AnalyticsExtraNotInstalled(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:  # pragma: no cover - install-time path
        raise AnalyticsExtraNotInstalled(
            "Install the analytics extra: `pip install -e .[analytics]`"
        ) from e
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def embed_text(text: str) -> tuple[bytes, int]:
    """Return (float32 packed bytes, dim) for ``text``."""
    vec = _model().encode([text], normalize_embeddings=True)[0]
    # vec is a numpy array; serialize as raw little-endian float32 bytes.
    return vec.astype("<f4").tobytes(), len(vec)


def unpack(buf: bytes, dim: int) -> list[float]:
    """Unpack the float32 bytes back into a Python list."""
    return list(struct.unpack(f"<{dim}f", buf))


def embedding_dim() -> int:
    return _DIM
