"""Pure statistics for judging Jev against human labels (growth Phase 0).

No I/O, no model calls, no third-party packages: the golden set is small (hundreds of rows), so plain
Python is fast enough and keeps the math auditable. Every function validates its inputs and raises
ValueError on anything it cannot score honestly (empty input, mismatched lengths, NaN).
"""
from __future__ import annotations

import math
from bisect import bisect_right


def _finite(values, name):
    out = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must contain finite numbers")
        out.append(float(value))
    return out


def quadratic_weighted_kappa(rater_a, rater_b, levels):
    """Cohen's kappa with quadratic weights for ordinal labels in range(levels).

    1.0 = perfect agreement, 0.0 = chance, negative = worse than chance. Returns None when both raters
    used a single identical level (kappa is undefined, not perfect)."""
    if not isinstance(levels, int) or levels < 2:
        raise ValueError("levels must be an integer >= 2")
    if len(rater_a) != len(rater_b) or not rater_a:
        raise ValueError("raters must be non-empty and the same length")
    for value in (*rater_a, *rater_b):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < levels:
            raise ValueError("labels must be integers in range(levels)")
    n = len(rater_a)
    observed = [[0] * levels for _ in range(levels)]
    for a, b in zip(rater_a, rater_b):
        observed[a][b] += 1
    hist_a = [sum(row) for row in observed]
    hist_b = [sum(observed[i][j] for i in range(levels)) for j in range(levels)]
    numerator = denominator = 0.0
    for i in range(levels):
        for j in range(levels):
            weight = ((i - j) ** 2) / ((levels - 1) ** 2)
            expected = hist_a[i] * hist_b[j] / n
            numerator += weight * observed[i][j]
            denominator += weight * expected
    if denominator == 0:
        return None
    return 1.0 - numerator / denominator


def expected_calibration_error(probabilities, outcomes, bins=10):
    """ECE for binary outcomes: weighted mean |accuracy - confidence| over equal-width probability bins."""
    probs = _finite(probabilities, "probabilities")
    if len(probs) != len(outcomes) or not probs:
        raise ValueError("probabilities and outcomes must be non-empty and the same length")
    if any(p < 0 or p > 1 for p in probs):
        raise ValueError("probabilities must be within [0, 1]")
    if any(o not in (0, 1, True, False) for o in outcomes):
        raise ValueError("outcomes must be 0 or 1")
    if not isinstance(bins, int) or bins < 1:
        raise ValueError("bins must be a positive integer")
    totals = [[0, 0.0, 0.0] for _ in range(bins)]
    for p, o in zip(probs, outcomes):
        index = min(bins - 1, int(p * bins))
        totals[index][0] += 1
        totals[index][1] += p
        totals[index][2] += int(o)
    n = len(probs)
    return sum(count / n * abs(hits / count - conf / count) for count, conf, hits in totals if count)


def isotonic_fit(probabilities, outcomes):
    """Pool-adjacent-violators isotonic regression.

    Returns a calibration map {"x": [...], "y": [...]} of non-decreasing breakpoints usable by
    `isotonic_apply`. Ties in x are merged first so the map is a function."""
    probs = _finite(probabilities, "probabilities")
    if len(probs) != len(outcomes) or not probs:
        raise ValueError("probabilities and outcomes must be non-empty and the same length")
    pairs = sorted(zip(probs, (float(int(o)) for o in outcomes)))
    merged = []
    for x, y in pairs:
        if merged and merged[-1][0] == x:
            merged[-1][1] += y
            merged[-1][2] += 1
        else:
            merged.append([x, y, 1])
    blocks = []  # [sum_y, weight, x_min, x_max]
    for x, y_sum, weight in merged:
        blocks.append([y_sum, weight, x, x])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            y2, w2, _, x2 = blocks.pop()
            blocks[-1][0] += y2
            blocks[-1][1] += w2
            blocks[-1][3] = x2
    xs, ys = [], []
    for y_sum, weight, x_min, x_max in blocks:
        value = y_sum / weight
        xs.extend([x_min, x_max] if x_max != x_min else [x_min])
        ys.extend([value, value] if x_max != x_min else [value])
    return {"x": xs, "y": ys}


def isotonic_apply(calibration, probability):
    """Map a raw probability through an isotonic calibration (linear between breakpoints, clamped)."""
    xs, ys = calibration.get("x") or [], calibration.get("y") or []
    if not xs or len(xs) != len(ys):
        raise ValueError("calibration map is empty or malformed")
    (p,) = _finite([probability], "probability")
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, p)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (p - x0) / (x1 - x0)


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation with average ranks for ties; None when either side is constant."""
    a, b = _finite(xs, "xs"), _finite(ys, "ys")
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("need two equally long series with at least two points")
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def ridge_fit(rows, targets, alpha=1.0):
    """Least squares with an L2 penalty (intercept unpenalised). Returns [intercept, w1, ..., wk]."""
    if not rows or len(rows) != len(targets):
        raise ValueError("rows and targets must be non-empty and the same length")
    k = len(rows[0])
    if any(len(r) != k for r in rows):
        raise ValueError("every row needs the same number of features")
    y = _finite(targets, "targets")
    X = [[1.0, *_finite(r, "rows")] for r in rows]
    size = k + 1
    a = [[sum(X[n][i] * X[n][j] for n in range(len(X))) + (alpha if i == j and i > 0 else 0.0) for j in range(size)] for i in range(size)]
    b = [sum(X[n][i] * y[n] for n in range(len(X))) for i in range(size)]
    for col in range(size):  # Gauss-Jordan with partial pivoting
        pivot = max(range(col, size), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("features are degenerate; add alpha or more varied rows")
        a[col], a[pivot] = a[pivot], a[col]
        b[col], b[pivot] = b[pivot], b[col]
        factor = a[col][col]
        a[col] = [v / factor for v in a[col]]
        b[col] /= factor
        for r in range(size):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col])]
                b[r] -= f * b[col]
    return b


def to_level(score, thresholds):
    """Index of the level for a score given ascending thresholds (len(thresholds)+1 levels)."""
    (s,) = _finite([score], "score")
    if list(thresholds) != sorted(thresholds):
        raise ValueError("thresholds must be ascending")
    return bisect_right(list(thresholds), s)


def fit_thresholds(scores, labels, levels, grid=41):
    """Ascending thresholds on [0, 1] that maximise quadratic weighted kappa between to_level(score)
    and labels. Greedy coordinate search over a fixed grid; deterministic."""
    s = _finite(scores, "scores")
    if len(s) != len(labels) or not s:
        raise ValueError("scores and labels must be non-empty and the same length")
    steps = [i / (grid - 1) for i in range(grid)]
    thresholds = [(i + 1) / levels for i in range(levels - 1)]

    def score_of(ts):
        kappa = quadratic_weighted_kappa([to_level(v, ts) for v in s], list(labels), levels)
        return -2.0 if kappa is None else kappa

    best = score_of(thresholds)
    improved = True
    while improved:
        improved = False
        for i in range(len(thresholds)):
            low = thresholds[i - 1] if i else 0.0
            high = thresholds[i + 1] if i + 1 < len(thresholds) else 1.0
            for candidate in steps:
                if not low <= candidate <= high or candidate == thresholds[i]:
                    continue
                trial = thresholds[:i] + [candidate] + thresholds[i + 1:]
                value = score_of(trial)
                if value > best + 1e-12:
                    best, thresholds, improved = value, trial, True
    return {"thresholds": thresholds, "kappa": None if best == -2.0 else best}
