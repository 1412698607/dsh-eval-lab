"""Conditional, pointwise 95% intervals; no pooling, imputation or hypothesis tests."""
from functools import lru_cache
import math
from statistics import NormalDist

from .formats import require


LEVEL = 0.95
ALPHA = 0.05
SMALL_SAMPLE = 30  # Display annotation, not a validity threshold.


def _result(method, n):
    return {"method": method, "confidenceLevel": LEVEL, "n": n, "status": "unavailable",
            "estimate": None, "lower": None, "upper": None, "reason": None,
            "warnings": ["small_sample"] if n < SMALL_SAMPLE else []}


def wilson_interval(successes, n):
    require(type(n) is int and type(successes) is int and 0 <= successes <= n <= 9007199254740991,
            "Wilson counts must be nonnegative safe integers with successes <= n")
    result = {**_result("wilson-score", n), "successes": successes}
    if n == 0:
        result["reason"] = "no_evaluable_samples"
        return result
    p = successes / n
    z = NormalDist().inv_cdf(1 - ALPHA / 2)
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    result.update(status="available", estimate=p, lower=0.0 if successes == 0 else max(0.0, center - half),
                  upper=1.0 if successes == n else min(1.0, center + half))
    return result


def paired_binary_interval(differences):
    require(all(type(value) is int and value in (-1, 0, 1) for value in differences), "Binary pair differences must be -1, 0 or 1")
    n = len(differences)
    result = {**_result("hoeffding-paired-binary", n),
              "discordantPairs": sum(value != 0 for value in differences)}
    if not n:
        result["reason"] = "no_evaluable_pairs"
        return result
    mean = sum(differences) / n
    # A paired Bernoulli difference is bounded by [-1, 1]. Two-sided Hoeffding inversion.
    half = math.sqrt(2 * math.log(2 / ALPHA) / n)
    result.update(status="available", estimate=mean, lower=max(-1.0, mean - half), upper=min(1.0, mean + half))
    result["warnings"].append("conservative_bound")
    return result


def _beta_fraction(a, b, x):
    # NIST DLMF 8.17.22-23, evaluated with a guarded continued fraction.
    tiny = 1e-300
    def guarded(value):
        return value if abs(value) >= tiny else math.copysign(tiny, value)
    c = 1.0
    d = 1 / guarded(1 - (a + b) * x / (a + 1))
    value = d
    for m in range(1, 501):
        even = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        odd = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        for coefficient in (even, odd):
            d = 1 / guarded(1 + coefficient * d)
            c = guarded(1 + coefficient / c)
            change = c * d
            value *= change
        if abs(change - 1) < 3e-14:
            return value
    raise ArithmeticError("Incomplete beta fraction did not converge")


def _beta_regularized(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    factor = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                      + a * math.log(x) + b * math.log1p(-x))
    value = (factor * _beta_fraction(a, b, x) / a if x < (a + 1) / (a + b + 2)
             else 1 - factor * _beta_fraction(b, a, 1 - x) / b)
    if not math.isfinite(value) or not -1e-12 <= value <= 1 + 1e-12:
        raise ArithmeticError("Invalid incomplete beta probability")
    return min(1.0, max(0.0, value))


@lru_cache(maxsize=256)
def _t_critical_95(df):
    require(type(df) is int and df >= 1, "Student t degrees of freedom must be positive")
    # P(|T_df| >= t) = I_{df/(df+t^2)}(df/2, 1/2). t(.975,1) < 16.
    low, high = 0.0, 16.0
    for _ in range(64):
        middle = (low + high) / 2
        tail = _beta_regularized(df / 2, 0.5, df / (df + middle * middle))
        if tail > ALPHA:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def paired_mean_interval(differences):
    n = len(differences)
    result = {**_result("paired-student-t", n), "degreesOfFreedom": n - 1 if n else None}
    result["warnings"].append("normal_difference_assumption")
    if not n:
        result["reason"] = "no_metric_pairs"
        return result
    try:
        require(all(type(value) in (int, float) and math.isfinite(value) for value in differences), "Pair differences must be finite numbers")
        # Remove a common offset before scaling so small, real spreads are not rounded away.
        anchor = differences[0]
        centered = [value - anchor for value in differences]
        try:
            finite_centered = all(math.isfinite(value) for value in centered)
        except OverflowError:
            finite_centered = False
        if not finite_centered:
            # Opposite extreme values may overflow on subtraction, yet a many-pair CI can be finite.
            anchor, centered = 0, differences
        scale = max(abs(value) for value in centered)
        scaled = [value / scale for value in centered] if scale else [0.0] * n
        mean = math.fsum(scaled) / n

        def restore(value):
            offset = value * scale
            if math.isfinite(offset):
                return math.fsum((anchor, offset))
            # Avoid overflow in the offset when its sum with the anchor is still representable.
            return math.fsum((anchor / scale, value)) * scale

        result["estimate"] = restore(mean)
        if n < 2:
            result["reason"] = "insufficient_pairs"
            return result
        deviation = math.sqrt(math.fsum((value - mean) ** 2 for value in scaled) / (n - 1))
        if deviation == 0:
            result["reason"] = "zero_observed_variance"
            return result
        critical = _t_critical_95(n - 1)
        margin = critical * deviation / math.sqrt(n)
        lower, upper = restore(mean - margin), restore(mean + margin)
        if not all(math.isfinite(value) for value in (result["estimate"], lower, upper)):
            raise OverflowError("Nonfinite interval")
        if lower == upper:
            result["reason"] = "precision_loss"
            return result
        result.update(status="available", lower=lower, upper=upper, criticalValue=critical)
    except (OverflowError, ArithmeticError):
        result.update(status="unavailable", lower=None, upper=None, reason="numeric_unavailable")
        if result["estimate"] is not None and not math.isfinite(result["estimate"]):
            result["estimate"] = None
    return result
