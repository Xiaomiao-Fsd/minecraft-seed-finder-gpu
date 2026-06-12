#!/usr/bin/env python3
"""Minecraft Java seed search orchestration framework.

Current practical mode: fast slime-density coarse prefilter.
For Java 26.2 / 26.2-pre1 biome and structure checks, plug in an external
checker (for example cubiomes or a custom C/Rust tool) through the JSON config.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.example.json"
C_HELPER_SRC = ROOT / "slime_prefilter.c"
C_HELPER_BIN = ROOT / "slime_prefilter"
CUDA_HELPER_SRC = ROOT / "slime_prefilter_cuda.cu"
CUDA_HELPER_BIN = ROOT / "slime_prefilter_cuda"


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def output_dir(config: Dict[str, Any]) -> Path:
    out = config.get("output", {})
    directory = Path(out.get("directory", "runs/default"))
    if not directory.is_absolute():
        directory = ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def compile_c_helper(force: bool = False) -> Path:
    if not C_HELPER_SRC.exists():
        raise FileNotFoundError(C_HELPER_SRC)
    if C_HELPER_BIN.exists() and not force and C_HELPER_BIN.stat().st_mtime >= C_HELPER_SRC.stat().st_mtime:
        return C_HELPER_BIN
    cmd = [
        "gcc",
        "-O3",
        "-march=native",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-o",
        str(C_HELPER_BIN),
        str(C_HELPER_SRC),
    ]
    print("[build]", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)
    return C_HELPER_BIN


def cuda_available() -> bool:
    return CUDA_HELPER_SRC.exists() and shutil.which("nvcc") is not None


def compile_cuda_helper(force: bool = False) -> Path:
    if not CUDA_HELPER_SRC.exists():
        raise FileNotFoundError(CUDA_HELPER_SRC)
    if shutil.which("nvcc") is None:
        raise RuntimeError("nvcc not found; install CUDA toolkit or use --backend cpu")
    if CUDA_HELPER_BIN.exists() and not force and CUDA_HELPER_BIN.stat().st_mtime >= CUDA_HELPER_SRC.stat().st_mtime:
        return CUDA_HELPER_BIN
    cmd = [
        "nvcc",
        "-O3",
        "-std=c++17",
        "-o",
        str(CUDA_HELPER_BIN),
        str(CUDA_HELPER_SRC),
    ]
    print("[build]", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)
    return CUDA_HELPER_BIN


def resolve_slime_backend(requested: str) -> str:
    requested = (requested or "auto").lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"unsupported slime backend: {requested}")
    if requested == "auto":
        return "cuda" if cuda_available() else "cpu"
    if requested == "cuda" and not cuda_available():
        raise RuntimeError("CUDA backend requested, but nvcc/CUDA helper is not available")
    return requested


def run_slime_prefilter(
    config: Dict[str, Any],
    *,
    start: int | None,
    count: int | None,
    append: bool,
    force_build: bool,
    backend: str = "auto",
) -> Path:
    seed_range = config.get("seed_range", {})
    pf = config.get("prefilter", {})
    out = config.get("output", {})

    start = int(seed_range.get("start", 0) if start is None else start)
    count = int(seed_range.get("count", 1000000) if count is None else count)

    circle_radius_chunks = max(1, int(round(float(pf.get("circle_radius_blocks", 128)) / 16.0)))
    search_radius_chunks = max(0, int(round(float(pf.get("search_radius_blocks", 10000)) / 16.0)))
    threshold = int(pf.get("threshold_chunks", 28))
    center_samples = int(pf.get("center_samples", 64))
    max_candidates = int(pf.get("max_candidates", 0))
    requested_backend = backend or str(pf.get("backend", "auto"))
    backend = resolve_slime_backend(requested_backend)

    odir = output_dir(config)
    csv_path = odir / out.get("candidates_csv", "candidates_slime.csv")
    helper = compile_cuda_helper(force=force_build) if backend == "cuda" else compile_c_helper(force=force_build)

    cmd = [
        str(helper),
        "--start", str(start),
        "--count", str(count),
        "--threshold", str(threshold),
        "--circle-radius-chunks", str(circle_radius_chunks),
        "--search-radius-chunks", str(search_radius_chunks),
        "--center-samples", str(center_samples),
        "--max-candidates", str(max_candidates),
        "--out", str(csv_path),
    ]
    if backend == "cuda":
        cuda_cfg = pf.get("cuda", {})
        cmd += [
            "--batch-size", str(int(cuda_cfg.get("batch_size", 1048576))),
            "--threads", str(int(cuda_cfg.get("threads", 256))),
        ]
    if append:
        cmd.append("--append")
    print(f"[backend] requested={requested_backend} using={backend}", file=sys.stderr)
    print("[run]", " ".join(cmd), file=sys.stderr)
    t0 = time.monotonic()
    subprocess.run(cmd, check=True)
    elapsed = time.monotonic() - t0
    print(f"[done] slime prefilter wrote {csv_path} in {elapsed:.1f}s", file=sys.stderr)
    write_checkpoint(config, {
        "last_mode": "slime-prefilter",
        "backend": backend,
        "requested_backend": requested_backend,
        "start": start,
        "count": count,
        "elapsed_seconds": elapsed,
        "seeds_per_second": count / elapsed if elapsed > 0 else None,
        "output": str(csv_path),
    })
    return csv_path


def write_checkpoint(config: Dict[str, Any], data: Dict[str, Any]) -> None:
    out = config.get("output", {})
    cp = output_dir(config) / out.get("checkpoint_file", "checkpoint.json")
    data = {**data, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    cp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_external_checker(seed: int, check_name: str, check_config: Dict[str, Any], global_config: Dict[str, Any]) -> Dict[str, Any]:
    """Call a configured external checker.

    The checker should read one JSON object from stdin and print one JSON object:
      input:  {"seed": 123, "edition": "java", "version": "26.2", "fallback_version": "26.2-pre1", "check": "...", "config": {...}}
      output: {"ok": true, "details": {...}}
    """
    ext = check_config.get("external_checker", {})
    command = ext.get("command")
    if not command:
        return {"ok": None, "skipped": True, "reason": f"no external checker configured for {check_name}"}
    payload = {
        "seed": seed,
        "edition": global_config.get("edition", "java"),
        "version": global_config.get("target_version", "26.2"),
        "fallback_version": global_config.get("fallback_version", "26.2-pre1"),
        "check": check_name,
        "config": check_config,
    }
    proc = subprocess.run(
        command if isinstance(command, list) else [command],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip(), "returncode": proc.returncode}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "checker did not return JSON", "stdout": proc.stdout[:1000]}


def refine_candidates(config: Dict[str, Any], candidates_csv: Path | None = None, limit: int | None = None) -> Path:
    odir = output_dir(config)
    out_cfg = config.get("output", {})
    if candidates_csv is None:
        candidates_csv = odir / out_cfg.get("candidates_csv", "candidates_slime.csv")
    results_csv = odir / out_cfg.get("results_csv", "results.csv")
    checks = config.get("checks", {})
    order = config.get("pipeline", {}).get("order", list(checks.keys()))

    with candidates_csv.open("r", encoding="utf-8", newline="") as src, results_csv.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        fields = list(reader.fieldnames or []) + ["refine_status", "failed_check", "details_json"]
        writer = csv.DictWriter(dst, fieldnames=fields)
        writer.writeheader()
        n = 0
        for row in reader:
            if limit is not None and n >= limit:
                break
            n += 1
            seed = int(row["seed"])
            failed = ""
            details: Dict[str, Any] = {}
            status = "passed_configured_checks"
            for check_name in order:
                check_cfg = checks.get(check_name, {})
                if not check_cfg.get("enabled", True):
                    continue
                if check_name == "dense_slime_chunks":
                    # The prefilter already checked a stricter or equal condition for sampled centers.
                    details[check_name] = {"ok": True, "note": "covered by slime prefilter candidate row"}
                    continue
                result = run_external_checker(seed, check_name, check_cfg, config)
                details[check_name] = result
                if result.get("skipped"):
                    status = "pending_external_checkers"
                    continue
                if result.get("ok") is not True:
                    failed = check_name
                    status = "failed"
                    break
            row.update({"refine_status": status, "failed_check": failed, "details_json": json.dumps(details, ensure_ascii=False)})
            writer.writerow(row)
    print(f"[done] refine wrote {results_csv}", file=sys.stderr)
    return results_csv


def summarize_csv(path: Path, top: int = 10) -> None:
    if not path.exists():
        print(f"missing: {path}")
        return
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"{path}: {len(rows)} rows")
    for row in rows[:top]:
        print(row)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minecraft Java 26.2 seed search framework")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="compile slime prefilter helper")
    p_build.add_argument("--force", action="store_true")
    p_build.add_argument("--backend", choices=["auto", "cpu", "cuda"], default="auto")

    p_slime = sub.add_parser("slime-prefilter", help="run fast sampled slime-density coarse filter")
    p_slime.add_argument("--start", type=int)
    p_slime.add_argument("--count", type=int)
    p_slime.add_argument("--append", action="store_true")
    p_slime.add_argument("--force-build", action="store_true")
    p_slime.add_argument("--backend", choices=["auto", "cpu", "cuda"], default="auto", help="auto uses CUDA when nvcc is available, otherwise CPU")

    p_refine = sub.add_parser("refine", help="run configured external checkers over candidate CSV")
    p_refine.add_argument("--candidates", type=Path)
    p_refine.add_argument("--limit", type=int)

    p_sum = sub.add_parser("summarize", help="show candidate/result CSV summary")
    p_sum.add_argument("path", type=Path)
    p_sum.add_argument("--top", type=int, default=10)

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    try:
        if args.cmd == "build":
            backend = resolve_slime_backend(args.backend)
            print(compile_cuda_helper(force=args.force) if backend == "cuda" else compile_c_helper(force=args.force))
        elif args.cmd == "slime-prefilter":
            print(run_slime_prefilter(cfg, start=args.start, count=args.count, append=args.append, force_build=args.force_build, backend=args.backend))
        elif args.cmd == "refine":
            print(refine_candidates(cfg, candidates_csv=args.candidates, limit=args.limit))
        elif args.cmd == "summarize":
            summarize_csv(args.path, top=args.top)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
