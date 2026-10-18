#!/usr/bin/env python3
"""Goal-oriented rasc replay benchmark.

Each scenario is an independent analysis goal. Steps are intentionally not merged
across goals. Every rasc step starts a fresh process, matching the supported CLI.
Python only orchestrates, validates output, randomizes trials, and computes stats.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BIN = Path(os.environ.get("RASC", ROOT / "target/release/rasc"))
APK = Path(os.environ.get("APK", "douyin-40.7.0.apk"))
OUT = ROOT / "results/rasc_outputs"
THREADS = os.environ.get("RASC_THREADS", "12")
TRIALS = 7
STARTUP_MS = 2.444


def rasc(*args: str) -> list[str]:
    return [str(BIN), *args]


SCENARIOS: dict[str, dict] = {
    "manifest_exported_components": {
        "intent": "Decode the manifest and list exported components.",
        "steps": [rasc("manifest", str(APK))],
        "expect": ["TTDownloaderProvider", "MicroGameContentProvider", "DataUnionActivity"],
    },
    "class_inventory": {
        "intent": "Build the class inventory used for APK scale and class location.",
        "steps": [rasc("classes", "--threads", THREADS, str(APK))],
        "expect": ["com.ss.android.ugc.aweme"],
    },
    "ttdownloader_provider_db": {
        "intent": "Locate the downloader table name, then inspect the provider that serves it.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "ttdownloaderClickId"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/downloadlib/addownload/TTDownloaderProvider;"),
        ],
        "expect": ["downloadUrl TEXT", "SQLiteDatabase", "query("],
    },
    "microgame_fileprovider_io": {
        "intent": "Locate the microgame file provider authority, then inspect its open/mode/delete methods.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "gamecp.micro.order.fileprovider"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/android/gamecp/business/orderdownload/gameresource/preload/MicroGameContentProvider;"),
        ],
        "expect": ["openFile", "ParcelFileDescriptor", "delete("],
    },
    "gameres_uri_permissions": {
        "intent": "Locate the game-resource endpoint, then inspect file lookup, URI permission and delete handling.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "com.ss.android.ugc.aweme/res_task"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/android/gamecp/business/download/predownload/GameResContentProvider;"),
        ],
        "expect": ["grantUriPermission", "fileUri", "delete("],
    },
    "secshare_provider_paths": {
        "intent": "Locate the shared-file root, inspect path construction, then find the caller-signature allowlist.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "sec_share_data_file"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/account/share/data/write/provider/SecShareDataProvider;"),
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "842F074BE474D152663F64DBA4B6321EE82F56361D5183EDD79E3026048C591A"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/02ju;"),
        ],
        "expect": ["getLastPathSegment", "new java.io.File", "com.ss.android.ucenter.cn"],
    },
    "appwidget_install_state": {
        "intent": "Locate the widget install-state key, then inspect the provider call that reads it.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "desktop_app_install_status"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/example/ug/explore/api/widget/utils/AppWidgetInstallFromOther;"),
        ],
        "expect": ["desktop_app_install_status", "getString", "Bundle"],
    },
    "honor_feedback_file_write": {
        "intent": "Locate the OEM feedback file name, then inspect the provider method that writes it.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "scalpel/message.dat"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/ugc/aweme/legoImp/task/scalpel/HonorFeedbackCP;"),
        ],
        "expect": ["AtomicFile", "honor_uuid", "log_switch"],
    },
    "data_union_prefs_read": {
        "intent": "Locate the data-union preference store, then inspect how its values are returned.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "sp_luckydog_union"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/ug/sdk/luckydog/tokenunion/dataunion/DataUnionActivity;"),
        ],
        "expect": ["key_union_value_key", "ResultReceiver", "getString"],
    },
    "aic_gzip_decode_limits": {
        "intent": "Locate the gzip-base64 preview entry, then inspect the decode path and its size handling.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "gzip-base64url"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/ugc/aweme/aicatom/AicAtomCardProtocolPreviewActivity;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0Cpb;"),
        ],
        "expect": ["GZIPInputStream", "readText", "messages"],
    },
    "widget_confirm_action": {
        "intent": "Locate the confirmation action key, then inspect the dialog construction and deep-link dispatch.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "positive_action"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/android/ug/expore/widget/autoinstall/WidgetConfirmActivity;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0ltK;"),
        ],
        "expect": ["positive_action", "DeepLinkHandlerActivity", "setData"],
    },
    "redbadge_update_path": {
        "intent": "Locate the desktop badge message key, then inspect the service and badge-count updates.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "desktop_red_badge"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/newmedia/redbadge/RedbadgeHandler;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0kOC;"),
        ],
        "expect": ["message_data", "applyCount", "removeCount"],
    },
    "crossover_token_handling": {
        "intent": "Locate crossover token handling, then inspect the Messenger service and activation reporting.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "TOKEN_CONSUME"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/ug/sdk/luckydog/task/CrossoverService;"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/ug/sdk/luckydog/task/CrossoverService$mHandler$1;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0lK7;"),
        ],
        "expect": ["36865", "exporter_aid", "re_ack install"],
    },
    "account_sync_adapter": {
        "intent": "Locate the SyncAdapter service, then inspect its binder and sync action.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", ".account.sync.adapter.service"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/sdk/account/sync/AccountSyncService;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0lt0;"),
        ],
        "expect": ["getSyncAdapterBinder", "account.sync.adapter.service"],
    },
    "luckycat_ssl_error_handling": {
        "intent": "Locate the WebView SSL-error handler and the JavaScript bridge names registered nearby.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "method", "onReceivedSslError", "--class", "LuckyCatWebViewClient"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/ug/sdk/luckycat/impl/browser/webview/LuckyCatWebViewClient;"),
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "LuckyCatBridge3"),
        ],
        "expect": ["SslErrorHandler", "proceed", "LuckyCatAuthBridge"],
    },
    "lmhttp_tls_setup": {
        "intent": "Locate the native-engine HTTP helper, then inspect its certificate, hostname and download handling.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "method", "setupHttpsTrust", "--class", "LMHttp"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/llama/cllama/engine/LMHttp;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0mZq;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0mZp;"),
            rasc("getclass", "--threads", THREADS, str(APK), "LX/0oM3;"),
        ],
        "expect": ["checkServerTrusted", "return true", "FileOutputStream"],
    },
    "cjpay_webview_config": {
        "intent": "Locate the payment WebView URL allowlist, QR routing and bridge registration.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "string", "http://atu-pay-test.shouqianpay.com"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/ss/android/ugc/aweme/cjpay/CJWebScanResultHandler;"),
            rasc("getclass", "--threads", THREADS, str(APK), "Lcom/bytedance/caijing/sdk/infra/base/impl/jsb/JsbServiceImpl$getH5JSBridgeHelper$1;"),
        ],
        "expect": ["aweme://webview", "http://", "JS2NativeBridge"],
    },
    "dynamic_loading_census": {
        "intent": "Count direct references to dynamic class loading, System.load and Runtime.exec.",
        "steps": [
            rasc("findrefs", "--threads", THREADS, str(APK), "type", "DexClassLoader"),
            rasc("findrefs", "--threads", THREADS, str(APK), "method", "load", "--class", "java.lang.System"),
            rasc("findrefs", "--threads", THREADS, str(APK), "method", "exec", "--class", "java.lang.Runtime"),
        ],
        "expect": ["DexClassLoader", "System", "Runtime"],
        "capability_note": "rasc can census direct references but cannot express DexSQL multi-hop call-graph joins.",
    },
}


def run_capture(cmd: list[str]) -> tuple[int, str, str, float]:
    start = time.perf_counter()
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr, (time.perf_counter() - start) * 1000


def run_timed(cmd: list[str]) -> float:
    start = time.perf_counter()
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return (time.perf_counter() - start) * 1000


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    validation = {}
    for name, spec in SCENARIOS.items():
        merged = []
        step_ms = []
        for index, cmd in enumerate(spec["steps"], 1):
            rc, stdout, stderr, elapsed = run_capture(cmd)
            step_ms.append(elapsed)
            (OUT / f"{name}.{index}.stdout.txt").write_text(stdout, encoding="utf-8")
            (OUT / f"{name}.{index}.stderr.txt").write_text(stderr, encoding="utf-8")
            merged.append(stdout)
            if rc != 0:
                raise SystemExit(f"validation failed: {name} step {index}: rc={rc}\n{stderr}")
        combined = "\n".join(merged)
        missing = [token for token in spec.get("expect", []) if token not in combined]
        validation[name] = {"step_ms": step_ms, "missing_tokens": missing}

    samples = {name: [] for name in SCENARIOS}
    order = [name for name in SCENARIOS for _ in range(TRIALS)]
    random.Random(1937).shuffle(order)
    for name in order:
        start = time.perf_counter()
        for cmd in SCENARIOS[name]["steps"]:
            run_timed(cmd)
        samples[name].append((time.perf_counter() - start) * 1000)

    results = {
        "binary": str(BIN),
        "apk": str(APK),
        "threads": int(THREADS),
        "trials": TRIALS,
        "startup_median_ms": STARTUP_MS,
        "scenarios": {},
        "validation": validation,
        "external_helpers": [
            "python3: subprocess orchestration, timing, randomization, medians, output-token validation",
            "No external APK parser, decompiler, SQL engine, JADX, or disassembler is used for rasc evidence",
        ],
    }
    for name, vals in samples.items():
        vals = sorted(vals)
        steps = len(SCENARIOS[name]["steps"])
        median = statistics.median(vals)
        results["scenarios"][name] = {
            "intent": SCENARIOS[name]["intent"],
            "step_count": steps,
            "median_end_to_end_ms": median,
            "median_minus_startup_ms_estimate": max(0.0, median - steps * STARTUP_MS),
            "min_ms": min(vals),
            "max_ms": max(vals),
            "samples_ms": vals,
            "commands": SCENARIOS[name]["steps"],
            "capability_note": SCENARIOS[name].get("capability_note"),
        }
    out_file = ROOT / "results/rasc_benchmark.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_file)
    for name, row in results["scenarios"].items():
        print(f"{name}\tsteps={row['step_count']}\te2e_ms={row['median_end_to_end_ms']:.3f}\tnet_est_ms={row['median_minus_startup_ms_estimate']:.3f}")


if __name__ == "__main__":
    main()
