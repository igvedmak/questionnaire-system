"""HDBSCAN-based clustering of free-text answers via their embeddings.

Why HDBSCAN: density-based, no `k` to choose, naturally surfaces an "noise"
cluster (-1) for one-of-a-kind answers — perfect for free-text survey
data where most answers are unique long-tail.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Cluster:
    """A group of semantically-similar answers."""
    cluster_id: int                 # -1 means "noise" / singletons
    size: int
    exemplar_text: str              # the answer closest to the centroid
    exemplar_questionnaire_id: str
    member_questionnaire_ids: list[str]


def cluster_freetext(
    items: list[tuple[str, str]],
    *,
    min_cluster_size: int = 3,
) -> list[Cluster]:
    """Cluster ``[(questionnaire_id, plaintext)]`` pairs.

    Tiny inputs are handled gracefully: with too few items, every answer
    ends up in the noise cluster.
    """
    if len(items) == 0:
        return []
    try:
        import hdbscan
        import numpy as np
    except ImportError as e:  # pragma: no cover - install-time path
        from .embeddings import AnalyticsExtraNotInstalled
        raise AnalyticsExtraNotInstalled(
            "Install the analytics extra: `pip install -e .[analytics]`"
        ) from e

    from .embeddings import embed_text

    vecs = []
    for _, text in items:
        buf, dim = embed_text(text)
        vec = np.frombuffer(buf, dtype="<f4")
        vecs.append(vec)
    matrix = np.vstack(vecs)

    if len(items) < min_cluster_size:
        # HDBSCAN refuses to cluster fewer points than min_cluster_size; treat all as noise.
        labels = np.full(len(items), -1, dtype=int)
    else:
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(matrix)

    grouped: dict[int, list[int]] = defaultdict(list)
    for idx, lbl in enumerate(labels):
        grouped[int(lbl)].append(idx)

    clusters: list[Cluster] = []
    for lbl, idxs in grouped.items():
        if lbl == -1:
            # Noise: report as a single cluster but pick any exemplar.
            ex_idx = idxs[0]
            clusters.append(Cluster(
                cluster_id=-1,
                size=len(idxs),
                exemplar_text=items[ex_idx][1],
                exemplar_questionnaire_id=items[ex_idx][0],
                member_questionnaire_ids=[items[i][0] for i in idxs],
            ))
            continue
        sub = matrix[idxs]
        centroid = sub.mean(axis=0)
        # Exemplar = nearest member to centroid by Euclidean distance.
        dists = ((sub - centroid) ** 2).sum(axis=1)
        ex_idx = idxs[int(dists.argmin())]
        clusters.append(Cluster(
            cluster_id=int(lbl),
            size=len(idxs),
            exemplar_text=items[ex_idx][1],
            exemplar_questionnaire_id=items[ex_idx][0],
            member_questionnaire_ids=[items[i][0] for i in idxs],
        ))
    # Largest non-noise clusters first; noise last.
    clusters.sort(key=lambda c: (c.cluster_id == -1, -c.size))
    return clusters
