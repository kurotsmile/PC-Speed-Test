#!/usr/bin/env python3
"""Sample plugin benchmark for PC Speed Test."""

from __future__ import annotations

import math
import time


def run_test() -> dict[str, float | str]:
    start = time.perf_counter()
    total = 0.0
    for idx in range(1, 300000):
        total += math.sqrt(idx)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    score = max(0.0, min(100.0, 100.0 - (elapsed_ms / 40.0)))
    return {
        "test": "python_math_loop",
        "elapsed_ms": round(elapsed_ms, 2),
        "score": round(score, 2),
        "checksum": round(total, 3),
    }
