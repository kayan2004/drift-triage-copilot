import numpy as np
import pytest

from app.db.models import SeverityEnum
from app.services.drift_calculator import (
    classify_chi2,
    classify_output_drift,
    classify_psi,
    compute_chi2_pvalue,
    compute_psi,
)


class TestComputePsi:
    def test_identical_distribution_returns_low_psi(self):
        # Use a large sample so observed proportions closely match reference
        rng = np.random.default_rng(42)
        reference_pct = [0.1, 0.2, 0.4, 0.2, 0.1]
        bin_edges = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        # Draw 5000 samples proportionally from each bin's midpoint
        midpoints = [0.5, 1.5, 2.5, 3.5, 4.5]
        current = np.concatenate([
            rng.uniform(lo, hi, int(p * 5000))
            for lo, hi, p in zip(bin_edges[:-1], bin_edges[1:], reference_pct, strict=False)
        ])
        psi = compute_psi(reference_pct, bin_edges, current)
        assert psi < 0.1

    def test_shifted_distribution_returns_high_psi(self):
        reference_pct = [0.8, 0.1, 0.05, 0.03, 0.02]
        bin_edges = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        current = np.array([4.5] * 100)  # all mass in last bin
        psi = compute_psi(reference_pct, bin_edges, current)
        assert psi > 0.2

    def test_empty_array_does_not_crash(self):
        reference_pct = [0.5, 0.5]
        bin_edges = [0.0, 1.0, 2.0]
        current = np.array([])
        psi = compute_psi(reference_pct, bin_edges, current)
        assert isinstance(psi, float)


class TestClassifyPsi:
    def test_ok(self):
        assert classify_psi(0.05) == SeverityEnum.ok

    def test_warn(self):
        assert classify_psi(0.15) == SeverityEnum.warn

    def test_critical(self):
        assert classify_psi(0.30) == SeverityEnum.critical

    def test_boundary_ok_warn(self):
        assert classify_psi(0.1) == SeverityEnum.warn

    def test_boundary_warn_critical(self):
        assert classify_psi(0.25) == SeverityEnum.critical


class TestComputeChi2Pvalue:
    def test_identical_distribution_high_pvalue(self):
        reference = {"a": 0.5, "b": 0.3, "c": 0.2}
        current = ["a"] * 50 + ["b"] * 30 + ["c"] * 20
        pvalue = compute_chi2_pvalue(reference, current)
        assert pvalue > 0.05

    def test_shifted_distribution_low_pvalue(self):
        reference = {"a": 0.9, "b": 0.1}
        current = ["b"] * 100  # completely flipped
        pvalue = compute_chi2_pvalue(reference, current)
        assert pvalue < 0.001

    def test_empty_list_returns_one(self):
        reference = {"a": 0.5, "b": 0.5}
        pvalue = compute_chi2_pvalue(reference, [])
        assert pvalue == 1.0

    def test_unseen_category_handled(self):
        reference = {"a": 0.5, "b": 0.5}
        current = ["a"] * 50 + ["c"] * 50  # "c" not in reference
        pvalue = compute_chi2_pvalue(reference, current)
        assert isinstance(pvalue, float)


class TestClassifyChi2:
    def test_ok(self):
        assert classify_chi2(0.1) == SeverityEnum.ok

    def test_warn(self):
        assert classify_chi2(0.003) == SeverityEnum.warn

    def test_critical(self):
        assert classify_chi2(0.0005) == SeverityEnum.critical

    def test_boundary_ok_warn(self):
        assert classify_chi2(0.005) == SeverityEnum.warn

    def test_boundary_warn_critical(self):
        assert classify_chi2(0.001) == SeverityEnum.critical


class TestClassifyOutputDrift:
    def test_ok(self):
        assert classify_output_drift(0.03) == SeverityEnum.ok

    def test_warn(self):
        assert classify_output_drift(0.10) == SeverityEnum.warn

    def test_critical(self):
        assert classify_output_drift(0.20) == SeverityEnum.critical

    def test_boundary_ok_warn(self):
        assert classify_output_drift(0.05) == SeverityEnum.ok

    def test_boundary_warn_critical(self):
        assert classify_output_drift(0.15) == SeverityEnum.warn
