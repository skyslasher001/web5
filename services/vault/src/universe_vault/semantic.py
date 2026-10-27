"""The Semantic layout: 3D positions where related items sit together, from their embeddings (ADR-0012).

numpy only, seconds at 50k items: a random projection to ≤ 256 dimensions, PCA to 32, k-means into
√(n/2) clusters, cluster centres spread in 3D by PCA, then each item placed around its centre along the
main directions of the data. Deterministic: the same vectors give the same positions.
"""

import math
from typing import Any

import numpy as np

RADIUS = 150.0  # how far the outermost cluster sits from the Core (world units, like the Project layout)
PROJECTED = 256
COMPONENTS = 32
MAX_CLUSTERS = 200
ITERATIONS = 15
SEED = 20261013


def _pca(x: np.ndarray, d: int) -> np.ndarray:
    """The data projected on its `d` main directions (largest variance first)."""
    centred = x - x.mean(axis=0)
    d = max(1, min(d, centred.shape[1], max(1, centred.shape[0] - 1)))
    cov = centred.T @ centred / max(1, centred.shape[0] - 1)
    values, vectors = np.linalg.eigh(cov)
    order = np.argsort(values)[::-1][:d]
    basis = vectors[:, order]
    # Fix each direction's sign so the result doesn't flip between runs.
    signs = np.sign(basis[np.abs(basis).argmax(axis=0), np.arange(basis.shape[1])])
    return centred @ (basis * np.where(signs == 0, 1, signs))


def _kmeans(z: np.ndarray, k: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = z.shape[0]
    # k-means++ seeding on a sample keeps it fast for 50k points.
    sample = z[rng.choice(n, size=min(n, 5000), replace=False)]
    centres = [sample[rng.integers(len(sample))]]
    nearest = np.full(len(sample), np.inf)
    for _ in range(1, k):
        nearest = np.minimum(nearest, ((sample - centres[-1]) ** 2).sum(axis=1))
        total = nearest.sum()
        centres.append(
            sample[rng.choice(len(sample), p=nearest / total)] if total > 0 else sample[rng.integers(len(sample))]
        )
    c = np.stack(centres)
    labels = np.zeros(n, dtype=np.int64)
    for _ in range(ITERATIONS):
        labels = _assign(z, c)
        # Every centre at once (one boolean mask per cluster per iteration was a quarter of the layout's time).
        sums = np.zeros_like(c)
        np.add.at(sums, labels, z)
        sizes = np.bincount(labels, minlength=k)
        filled = sizes > 0  # an empty cluster keeps its centre
        c[filled] = sums[filled] / sizes[filled, None]
    return c, _assign(z, c)


def _assign(z: np.ndarray, c: np.ndarray, chunk: int = 8192) -> np.ndarray:
    out = np.empty(z.shape[0], dtype=np.int64)
    c_sq = (c**2).sum(axis=1)
    for start in range(0, z.shape[0], chunk):
        part = z[start : start + chunk]
        out[start : start + chunk] = (c_sq[None, :] - 2 * part @ c.T).argmin(axis=1)
    return out


def layout(vectors: Any) -> np.ndarray:
    """(n, 3) float32 positions for (n, dim) vectors."""
    # The input is never copied whole: at 50k × 1024 one float64 copy is 400 MB, and filling fresh memory
    # was most of the time on CI's Windows runner (2026-10-27). Project first, then divide by the norms:
    # (x / |x|) @ R == (x @ R) / |x|, so the cosine geometry is the same.
    x = np.asarray(vectors)
    if x.dtype not in (np.float32, np.float64):
        x = x.astype(np.float64)
    n = x.shape[0]
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32)
    if n == 1:
        return np.array([[RADIUS * 0.3, 0.0, 0.0]], dtype=np.float32)
    rng = np.random.default_rng(SEED)
    norms = np.sqrt(np.einsum("ij,ij->i", x, x, dtype=np.float64))[:, None]
    if x.shape[1] > PROJECTED:
        x = x @ (rng.standard_normal((x.shape[1], PROJECTED)) / math.sqrt(PROJECTED)).astype(x.dtype)
    x = x.astype(np.float64) / np.where(norms == 0, 1, norms)  # cosine geometry, like search
    z = _pca(x, COMPONENTS)
    k = int(min(MAX_CLUSTERS, max(1, round(math.sqrt(n / 2)))))
    centres, labels = _kmeans(z, k, rng)

    # Cluster centres in 3D: their own main directions, scaled so the spread fills RADIUS.
    if k >= 4:
        c3 = _pca(centres, 3)
    else:
        c3 = np.zeros((k, 3))
        c3[:, : min(3, centres.shape[1])] = centres[:, :3]
    if c3.shape[1] < 3:
        c3 = np.pad(c3, ((0, 0), (0, 3 - c3.shape[1])))
    spread = np.abs(c3).max() or 1.0
    c3 = c3 / spread * RADIUS

    # Items around their centre: the residual's first three components, scaled to the cluster's share of space.
    residual = z - centres[labels]
    r3 = residual[:, :3] if residual.shape[1] >= 3 else np.pad(residual, ((0, 0), (0, 3 - residual.shape[1])))
    scale = np.abs(r3).max() or 1.0
    room = RADIUS / max(2.0, k ** (1 / 3)) * 0.6
    positions = c3[labels] + r3 / scale * room
    return positions.astype(np.float32)
