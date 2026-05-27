"""Smoke test for the backend test runner.

Verifies pytest is installed and discovers tests. Real AC tests land
alongside Wave 1 implementation — see docs/acceptance-criteria.md.
"""

import sys


def test_pytest_runs():
    assert True


def test_python_version_supports_backend():
    assert sys.version_info >= (3, 10)
