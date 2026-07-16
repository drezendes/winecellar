"""Taste-map projection: 7-dim style vectors → 2-D, stdlib only.

PCA via power iteration on the 7x7 covariance matrix — ~200 wines x 7 dims
is trivial, so no numpy and no caching until it ever isn't. Axis labels are
derived from the PCA loadings and only claimed when one attribute clearly
dominates the axis (see AXIS_DOMINANCE); otherwise the axis stays unlabeled
rather than inventing a name the math doesn't support.
"""

import math

from assistant.schemas import STYLE_SCALES

# Pole wording per attribute: (low end, high end).
ATTR_POLES = {
    "body": ("lighter", "fuller"),
    "acidity": ("softer", "brighter"),
    "tannin": ("supple", "grippy"),
    "sweetness": ("drier", "sweeter"),
    "fruit_savory": ("fruity", "savory"),
    "oak": ("unoaked", "oaky"),
    "intensity": ("delicate", "powerful"),
}
AXIS_DOMINANCE = 0.55  # |loading| an attribute needs to name an axis
NEIGHBOR_COUNT = 5


def style_row(style_vector):
    """A wine's JSON style vector → ordered float list (missing scales → 5)."""
    return [float(style_vector.get(scale, 5)) for scale in STYLE_SCALES]


def _matvec(matrix, vector):
    return [sum(row[j] * vector[j] for j in range(len(vector))) for row in matrix]


def _norm(vector):
    return math.sqrt(sum(component * component for component in vector))


def _top_eigen(matrix, iterations=300):
    """Dominant eigenvector/value by power iteration. (zero-vector, 0) if degenerate."""
    n = len(matrix)
    vec = [1.0 + 0.1 * i for i in range(n)]  # asymmetric seed avoids orthogonal starts
    for _ in range(iterations):
        nxt = _matvec(matrix, vec)
        norm = _norm(nxt)
        if norm < 1e-12:
            return [0.0] * n, 0.0
        vec = [component / norm for component in nxt]
    eigenvalue = sum(v * mv for v, mv in zip(vec, _matvec(matrix, vec)))
    return vec, eigenvalue


def _principal_axes(rows):
    """Top two principal axes of the (mean-centered) rows."""
    n, dims = len(rows), len(rows[0])
    means = [sum(row[j] for row in rows) / n for j in range(dims)]
    centered = [[row[j] - means[j] for j in range(dims)] for row in rows]
    cov = [
        [sum(row[i] * row[j] for row in centered) / max(n - 1, 1) for j in range(dims)]
        for i in range(dims)
    ]
    axis1, value1 = _top_eigen(cov)
    deflated = [
        [cov[i][j] - value1 * axis1[i] * axis1[j] for j in range(dims)] for i in range(dims)
    ]
    axis2, _ = _top_eigen(deflated)
    return centered, axis1, axis2


def _axis_label(axis):
    """('low pole', 'high pole') when one attribute dominates the axis, else None."""
    norm = _norm(axis)
    if norm < 1e-9:
        return None
    loadings = [component / norm for component in axis]
    magnitude, index = max((abs(value), i) for i, value in enumerate(loadings))
    if magnitude < AXIS_DOMINANCE:
        return None
    low, high = ATTR_POLES[STYLE_SCALES[index]]
    return (high, low) if loadings[index] < 0 else (low, high)


def _spread(values, lo=8.0, hi=92.0):
    """Normalize to [lo, hi]; a degenerate (constant) axis centers everything."""
    vmin, vmax = min(values), max(values)
    if vmax - vmin < 1e-9:
        return [(lo + hi) / 2 for _ in values]
    return [lo + (v - vmin) / (vmax - vmin) * (hi - lo) for v in values]


def project(items):
    """[(key, style_vector_json)] → positions dict + axis labels.

    Returns {"positions": {key: (x, y)}, "x_axis": poles|None, "y_axis": poles|None}
    with x/y in [8, 92] (viewBox percent, padded).
    """
    if not items:
        return {"positions": {}, "x_axis": None, "y_axis": None}
    rows = [style_row(vector) for _, vector in items]
    if len(items) == 1:
        return {"positions": {items[0][0]: (50.0, 50.0)}, "x_axis": None, "y_axis": None}

    centered, axis1, axis2 = _principal_axes(rows)
    xs = _spread([sum(r * a for r, a in zip(row, axis1)) for row in centered])
    ys = _spread([sum(r * a for r, a in zip(row, axis2)) for row in centered])
    return {
        "positions": {key: (x, y) for (key, _), x, y in zip(items, xs, ys)},
        "x_axis": _axis_label(axis1),
        "y_axis": _axis_label(axis2),
    }


def neighbors(focus_vector, items, count=NEIGHBOR_COUNT):
    """Keys of the `count` nearest items to focus_vector (7-dim euclidean)."""
    focus_row = style_row(focus_vector)
    scored = sorted(
        (
            (math.dist(focus_row, style_row(vector)), key)
            for key, vector in items
        ),
    )
    return [key for _, key in scored[:count]]
