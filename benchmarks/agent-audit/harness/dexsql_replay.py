#!/usr/bin/env python3
"""Benchmark DexSQL v0.1.1 MCP with thread tuning and compact responses."""

from __future__ import annotations

import hashlib
import json
import os
import random
import statistics
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BIN = Path(os.environ.get("DEXSQL", ROOT / "dexsql"))
APK = os.environ.get("APK", "douyin-40.7.0.apk")
OUT = ROOT / "results/dexsql_outputs"
THREAD_CANDIDATES = (0, 1, 2, 4, 8, 12, 16)
THREAD_TRIALS = 3
TRIALS = 7


class McpClient:
    def __init__(self, threads: int):
        self.p = subprocess.Popen(
            [str(BIN), "--threads", str(threads), "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.next_id = 1
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "dexsql-v011-benchmark", "version": "1"},
            },
        )
        self.notify("notifications/initialized", {})

    def _send(self, payload: dict) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        ident = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        assert self.p.stdout is not None
        while True:
            line = self.p.stdout.readline()
            if not line:
                stderr = self.p.stderr.read() if self.p.stderr else ""
                raise RuntimeError(f"MCP server exited while waiting for {method}: {stderr}")
            msg = json.loads(line)
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(f"MCP error for {method}: {msg['error']}")
                return msg["result"]

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def tool(self, name: str, arguments: dict) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"tool {name} failed: {result}")
        return result

    def close(self) -> None:
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(timeout=5)


def structured(result: dict) -> dict:
    value = result.get("structuredContent")
    if isinstance(value, dict):
        return value
    for item in result.get("content", []):
        if item.get("type") == "text":
            return json.loads(item["text"])
    raise RuntimeError(f"no structured result: {result}")


def open_dataset(client: McpClient) -> tuple[str, float, dict]:
    start = time.perf_counter()
    result = client.tool("open_dataset", {"inputs": [APK], "timeout_ms": 60000})
    wall = (time.perf_counter() - start) * 1000
    body = structured(result)
    return body["dataset_id"], wall, body


def scenario_functions(client: McpClient, dataset: str):
    def q(sql, limit=100):
        if isinstance(sql, str):
            sql = [sql]
        return client.tool(
            "query",
            {
                "dataset_id": dataset,
                "sql": sql,
                "limit": limit,
                "max_bytes": 65536,
                "timeout_ms": 60000,
                "timing": True,
                "compact": True,
            },
        )

    def d(file_id, method_idx):
        return client.tool(
            "decode",
            {
                "dataset_id": dataset,
                "file_id": file_id,
                "method_idx": method_idx,
                "mode": "smali",
                "max_lines": 1000,
                "max_bytes": 131072,
                "timeout_ms": 60000,
                "compact": True,
            },
        )

    return {
        "manifest_exported_components": lambda: [
            client.tool(
                "get_manifest_components",
                {
                    "dataset_id": dataset,
                    "only_exported": True,
                    "limit": 200,
                    "max_bytes": 131072,
                    "timeout_ms": 60000,
                    "compact": True,
                },
            )
        ],
        "ttdownloader_provider_db": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value LIKE '%ttdownloaderClickId%' ORDER BY file_id,method_idx", 20),
            d(31, 41788),
        ],
        "microgame_fileprovider_io": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value LIKE '%gamecp.micro.order.fileprovider%' ORDER BY file_id,method_idx", 20),
            d(31, 35118), d(31, 35112), d(31, 35114),
        ],
        "gameres_uri_permissions": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='com.ss.android.ugc.aweme/res_task' ORDER BY file_id,method_idx", 20),
            d(31, 34700), d(31, 34702),
        ],
        "secshare_provider_paths": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='sec_share_data_file' ORDER BY file_id,method_idx", 20),
            d(12, 44130),
            q([
                "SELECT file_id,method_idx,method,value FROM method_strings WHERE method_class='LX/02ju;' ORDER BY value,file_id,method_idx",
                "SELECT file_id,method_idx,method,value FROM method_strings WHERE value='842F074BE474D152663F64DBA4B6321EE82F56361D5183EDD79E3026048C591A' ORDER BY file_id,method_idx",
            ], 20),
        ],
        "appwidget_install_state": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='desktop_app_install_status' ORDER BY file_id,method_idx", 20), d(12, 41578)
        ],
        "honor_feedback_file_write": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='scalpel/message.dat' ORDER BY file_id,method_idx", 20), d(12, 49769)
        ],
        "data_union_prefs_read": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='sp_luckydog_union' ORDER BY file_id,method_idx", 20), d(12, 40413)
        ],
        "aic_gzip_decode_limits": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='gzip-base64url' ORDER BY file_id,method_idx", 20), d(32, 50214), d(49, 20719)
        ],
        "widget_confirm_action": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='positive_action' ORDER BY file_id,method_idx", 20), d(12, 35331), d(12, 35326), d(12, 28114)
        ],
        "redbadge_update_path": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='desktop_red_badge' ORDER BY file_id,method_idx", 20), d(12, 44449), d(12, 8035)
        ],
        "crossover_token_handling": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value LIKE '%TOKEN_CONSUME%' ORDER BY file_id,method_idx", 20), d(12, 40400), d(12, 20829)
        ],
        "account_sync_adapter": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='.account.sync.adapter.service' ORDER BY file_id,method_idx", 20), d(12, 40208), d(12, 28038)
        ],
        "luckycat_ssl_error_handling": lambda: [
            q("SELECT file_id,method_idx,descriptor FROM methods WHERE class_descriptor='Lcom/bytedance/ug/sdk/luckycat/impl/browser/webview/LuckyCatWebViewClient;' AND name='onReceivedSslError' ORDER BY file_id,method_idx", 20),
            d(30, 47635),
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='LuckyCatBridge3' ORDER BY file_id,method_idx", 100),
        ],
        "lmhttp_tls_setup": lambda: [
            q("SELECT file_id,method_idx,descriptor FROM methods WHERE class_descriptor='Lcom/bytedance/llama/cllama/engine/LMHttp;' AND name IN ('setupHttpsTrust','syncGetBinary','trustAllCertificates') ORDER BY file_id,method_idx", 20),
            d(13, 42268), d(13, 8793), d(13, 8790), d(13, 30699),
        ],
        "cjpay_webview_config": lambda: [
            q("SELECT file_id,method_idx,method,value FROM method_strings WHERE value='http://atu-pay-test.shouqianpay.com' ORDER BY file_id,method_idx", 20), d(20, 44739), d(30, 38954)
        ],
        "dynamic_loading_census": lambda: [
            q([
                "SELECT DISTINCT file_id,method_idx,method,callee FROM method_calls WHERE callee_class='Ldalvik/system/DexClassLoader;' ORDER BY file_id,method_idx LIMIT 200",
                "SELECT DISTINCT file_id,method_idx,method,callee FROM method_calls WHERE callee='Ljava/lang/System;->load(Ljava/lang/String;)V' ORDER BY file_id,method_idx LIMIT 200",
                "SELECT DISTINCT file_id,method_idx,method,callee FROM method_calls WHERE callee='Ljava/lang/Runtime;->exec(Ljava/lang/String;)Ljava/lang/Process;' ORDER BY file_id,method_idx LIMIT 200",
            ], 200)
        ],
    }


def tune_threads():
    rows = {}
    order = [n for n in THREAD_CANDIDATES for _ in range(THREAD_TRIALS)]
    random.Random(1937).shuffle(order)
    for threads in order:
        client = McpClient(threads)
        try:
            dataset, open_ms, body = open_dataset(client)
            funcs = scenario_functions(client, dataset)
            start = time.perf_counter()
            funcs["ttdownloader_provider_db"]()
            hot_ms = (time.perf_counter() - start) * 1000
            client.tool("close_dataset", {"dataset_id": dataset})
            row = rows.setdefault(threads, {"open_ms": [], "hot_ms": [], "prepare_ms": []})
            row["open_ms"].append(open_ms)
            row["hot_ms"].append(hot_ms)
            row["prepare_ms"].append(float(body["prepare_ms"]))
        finally:
            client.close()
    summary = {}
    for threads, row in sorted(rows.items()):
        summary[str(threads)] = {
            "open_median_ms": statistics.median(row["open_ms"]),
            "hot_probe_median_ms": statistics.median(row["hot_ms"]),
            "prepare_median_ms": statistics.median(row["prepare_ms"]),
            "composite_median_ms": statistics.median(
                [a + b for a, b in zip(row["open_ms"], row["hot_ms"])]
            ),
            "samples": row,
        }
    best = min(summary, key=lambda k: summary[k]["composite_median_ms"])
    return int(best), summary


def startup_bench(threads: int):
    cli = []
    mcp = []
    for _ in range(30):
        start = time.perf_counter()
        subprocess.run([str(BIN), "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cli.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        client = McpClient(threads)
        mcp.append((time.perf_counter() - start) * 1000)
        client.close()
    return {
        "cli_version_median_ms": statistics.median(cli),
        "cli_version_samples_ms": sorted(cli),
        "mcp_initialize_median_ms": statistics.median(mcp),
        "mcp_initialize_samples_ms": sorted(mcp),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    best_threads, thread_sweep = tune_threads()
    startup = startup_bench(best_threads)
    client = McpClient(best_threads)
    try:
        dataset, open_wall_ms, open_body = open_dataset(client)
        funcs = scenario_functions(client, dataset)
        validation = {}
        for name, fn in funcs.items():
            start = time.perf_counter()
            results = fn()
            validation[name] = {
                "wall_ms": (time.perf_counter() - start) * 1000,
                "result_bytes": len(json.dumps(results, ensure_ascii=False)),
            }
            for idx, result in enumerate(results, 1):
                (OUT / f"{name}.{idx}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        samples = {name: [] for name in funcs}
        order = [name for name in funcs for _ in range(TRIALS)]
        random.Random(1937).shuffle(order)
        for name in order:
            start = time.perf_counter()
            funcs[name]()
            samples[name].append((time.perf_counter() - start) * 1000)

        client.tool("close_dataset", {"dataset_id": dataset})
    finally:
        client.close()

    report = {
        "version": subprocess.run([str(BIN), "--version"], capture_output=True, text=True).stdout.strip(),
        "binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
        "best_threads": best_threads,
        "thread_sweep": thread_sweep,
        "startup": startup,
        "open_wall_ms": open_wall_ms,
        "open_result": open_body,
        "trials": TRIALS,
        "compact": True,
        "scenarios": {},
        "validation": validation,
    }
    for name, values in samples.items():
        values.sort()
        report["scenarios"][name] = {
            "median_wall_ms": statistics.median(values),
            "min_ms": min(values),
            "max_ms": max(values),
            "samples_ms": values,
        }
    path = ROOT / "results/dexsql_benchmark.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    print("best_threads", best_threads)
    for name, row in report["scenarios"].items():
        print(f"{name}\t{row['median_wall_ms']:.3f} ms")


if __name__ == "__main__":
    main()
