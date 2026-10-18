#!/usr/bin/env python3
"""Time the complete 17-goal suite end to end for DexSQL and rasc.

DexSQL: one new MCP process per trial (initialize, open_dataset, every goal, close).
rasc: every supported CLI step of every goal as a fresh process (it has no session mode).
The class inventory goal is excluded on both sides (see README).

Environment: APK, DEXSQL, RASC, DEXSQL_THREADS (default 16), RASC_THREADS (default 12).
"""

from __future__ import annotations

import json
import os
import statistics
import time

os.environ.setdefault("APK", "douyin-40.7.0.apk")

import dexsql_replay as dx  # noqa: E402
import rasc_replay as rs  # noqa: E402

TRIALS = 7
DEXSQL_THREADS = int(os.environ.get("DEXSQL_THREADS", "16"))
EXCLUDED = ["class_inventory"]


def dexsql_trial() -> dict:
    start = time.perf_counter()
    client = dx.McpClient(DEXSQL_THREADS)
    init_ms = (time.perf_counter() - start) * 1000
    try:
        dataset, open_ms, body = dx.open_dataset(client)
        hot = time.perf_counter()
        for goal in dx.scenario_functions(client, dataset).values():
            goal()
        hot_ms = (time.perf_counter() - hot) * 1000
        client.tool("close_dataset", {"dataset_id": dataset})
    finally:
        client.close()
    return {
        "mcp_init_ms": init_ms,
        "open_ms": open_ms,
        "prepare_ms": float(body["prepare_ms"]),
        "hot_suite_ms": hot_ms,
        "total_process_ms": (time.perf_counter() - start) * 1000,
    }


def rasc_trial() -> dict:
    steps = [cmd for name, spec in rs.SCENARIOS.items() if name not in EXCLUDED for cmd in spec["steps"]]
    start = time.perf_counter()
    for cmd in steps:
        rs.run_timed(cmd)
    return {"total_process_ms": (time.perf_counter() - start) * 1000, "process_count": len(steps)}


def main() -> None:
    dexsql, rasc = [], []
    for trial in range(1, TRIALS + 1):
        # Alternate which tool runs first so neither always inherits a warmer cache.
        pair = (dexsql_trial, rasc_trial) if trial % 2 else (rasc_trial, dexsql_trial)
        for fn in pair:
            row = {"trial": trial, **fn()}
            (dexsql if fn is dexsql_trial else rasc).append(row)
    medians = {k: statistics.median(r[k] for r in dexsql) for k in dexsql[0] if k != "trial"}
    out = dx.ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "dexsql_whole_suite.json").write_text(json.dumps(
        {"threads": DEXSQL_THREADS, "trials": dexsql, "medians": medians}, indent=1))
    (out / "rasc_whole_suite.json").write_text(json.dumps(
        {"threads": int(rs.THREADS), "excluded": EXCLUDED, "trials": rasc,
         "median_total_process_ms": statistics.median(r["total_process_ms"] for r in rasc)}, indent=1))
    print("dexsql", medians)
    print("rasc", statistics.median(r["total_process_ms"] for r in rasc))


if __name__ == "__main__":
    main()
