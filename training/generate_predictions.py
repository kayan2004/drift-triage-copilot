"""
Generates prediction batches to test drift detection at three severity levels.
Samples ok batch from actual training distributions in reference_stats.json.

Usage:
    uv run python generate_predictions.py
"""

import asyncio
import json
import random
from pathlib import Path

import httpx

MODEL_SERVICE_URL = "http://localhost:8000"
WINDOW_SIZE = 500
BATCH_SIZE = WINDOW_SIZE + 10

REF = json.loads((Path(__file__).parent / "reference_stats.json").read_text())


def sample_bin(bin_edges: list, reference_pct: list) -> float:
    """Sample a value from a binned reference distribution.
    Only samples from bins with non-zero reference probability to avoid
    inflating PSI with values the reference considers impossible.
    """
    valid = [(i, p) for i, p in enumerate(reference_pct) if p > 0]
    indices, weights = zip(*valid)
    idx = random.choices(indices, weights=weights)[0]
    return round(random.uniform(bin_edges[idx], bin_edges[idx + 1]), 4)


def sample_bin_warn(bin_edges: list, reference_pct: list) -> float:
    """Sample from a flattened reference distribution — gives PSI ~0.1–0.2.
    Uses power 0.65 on weights so low-frequency bins get more mass and
    high-frequency bins less, without ever landing in zero-probability bins.
    """
    shifted = [p ** 0.65 for p in reference_pct]
    valid = [(i, w) for i, w in enumerate(shifted) if reference_pct[i] > 0]
    indices, weights = zip(*valid)
    idx = random.choices(indices, weights=weights)[0]
    return round(random.uniform(bin_edges[idx], bin_edges[idx + 1]), 4)


def sample_cat(proportions: dict) -> str:
    """Sample a category using training proportions as weights."""
    cats = list(proportions.keys())
    weights = list(proportions.values())
    return random.choices(cats, weights=weights)[0]


def ok_features() -> dict:
    """Sample from the actual training distribution — expect ok severity."""
    num = REF["numerics"]
    cat = REF["categoricals"]
    return {
        "age":             int(sample_bin(num["age"]["bin_edges"], num["age"]["reference_pct"])),
        "campaign":        max(1, int(sample_bin(num["campaign"]["bin_edges"], num["campaign"]["reference_pct"]))),
        "previous":        int(sample_bin(num["previous"]["bin_edges"], num["previous"]["reference_pct"])),
        "pdays_contacted": random.choices([0, 1], weights=[0.962, 0.038])[0],
        "emp_var_rate":    sample_bin(num["emp_var_rate"]["bin_edges"], num["emp_var_rate"]["reference_pct"]),
        "cons_price_idx":  sample_bin(num["cons_price_idx"]["bin_edges"], num["cons_price_idx"]["reference_pct"]),
        "cons_conf_idx":   sample_bin(num["cons_conf_idx"]["bin_edges"], num["cons_conf_idx"]["reference_pct"]),
        "euribor3m":       sample_bin(num["euribor3m"]["bin_edges"], num["euribor3m"]["reference_pct"]),
        "nr_employed":     sample_bin(num["nr_employed"]["bin_edges"], num["nr_employed"]["reference_pct"]),
        "job":             sample_cat(cat["job"]),
        "marital":         sample_cat(cat["marital"]),
        "education":       sample_cat(cat["education"]),
        "default":         sample_cat(cat["default"]),
        "housing":         sample_cat(cat["housing"]),
        "loan":            sample_cat(cat["loan"]),
        "contact":         sample_cat(cat["contact"]),
        "month":           sample_cat(cat["month"]),
        "day_of_week":     sample_cat(cat["day_of_week"]),
        "poutcome":        sample_cat(cat["poutcome"]),
    }


def warn_features() -> dict:
    """Shift only cons_conf_idx — gives PSI ~0.13 (warn) without moving output_drift."""
    f = ok_features()
    num = REF["numerics"]
    f["cons_conf_idx"] = sample_bin_warn(
        num["cons_conf_idx"]["bin_edges"], num["cons_conf_idx"]["reference_pct"]
    )
    f["nr_employed"] = sample_bin_warn(
        num["nr_employed"]["bin_edges"], num["nr_employed"]["reference_pct"]
    )
    return f


def critical_features() -> dict:
    """Heavily shifted outside training range — expect critical severity."""
    f = ok_features()
    f["euribor3m"]       = round(random.uniform(5.5, 8.0), 4)
    f["emp_var_rate"]    = round(random.uniform(2.0, 4.5), 4)
    f["cons_price_idx"]  = round(random.uniform(95.5, 97.5), 4)
    f["cons_conf_idx"]   = round(random.uniform(-15.0, -5.0), 4)
    f["nr_employed"]     = round(random.uniform(5300.0, 5500.0), 1)
    f["month"]           = random.choices(
        ["oct", "nov", "dec"], weights=[30, 40, 30]
    )[0]
    f["poutcome"]        = random.choices(
        ["nonexistent", "failure", "success"], weights=[10, 85, 5]
    )[0]
    f["contact"]         = "telephone"
    return f


async def send_one(client: httpx.AsyncClient, features: dict) -> bool:
    try:
        resp = await client.post(f"{MODEL_SERVICE_URL}/predict/", json=features, timeout=15.0)
        return resp.status_code == 200
    except Exception:
        return False


async def send_batch(label: str, feature_fn, n: int) -> None:
    print(f"\n[{label}] Sending {n} predictions...")
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[send_one(client, feature_fn()) for _ in range(n)])
    print(f"  {sum(results)}/{n} succeeded")


async def compute_and_print() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{MODEL_SERVICE_URL}/drift/compute", timeout=30.0)
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text}")
        return "error"
    r = resp.json()
    top_psi = sorted(r["psi_scores"].items(), key=lambda x: x[1], reverse=True)[:3]
    low_chi2 = sorted(r["chi2_scores"].items(), key=lambda x: x[1])[:3]
    print(f"  severity:     {r['severity']}")
    print(f"  output_drift: {r['output_drift']:.4f}")
    print(f"  top PSI:      {top_psi}")
    print(f"  low chi2 p:   {low_chi2}")
    return r["severity"]


async def main() -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{MODEL_SERVICE_URL}/health")
        resp.raise_for_status()
        print(f"model_service healthy — model v{resp.json()['model_version']}")

    for label, feature_fn, expected in [
        ("OK",       ok_features,       "ok"),
        ("WARN",     warn_features,     "warn"),
        ("CRITICAL", critical_features, "critical"),
    ]:
        await send_batch(label, feature_fn, BATCH_SIZE)
        severity = await compute_and_print()
        match = "✓" if severity == expected else "✗"
        print(f"  expected: {expected} | got: {severity} {match}")


if __name__ == "__main__":
    asyncio.run(main())
