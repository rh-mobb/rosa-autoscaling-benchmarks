#!/usr/bin/env python3
"""
scripts/lib/bench.py

Common utilities for ROSA autoscaling benchmark test scripts:
- Standard argument parsing
- Milestone recording (delegates to record-event.py)
- Checkpoint management (delegates to checkpoint.py)
- SIGINT handling with cleanup callbacks
- Structured result output
- HTML report writing to reports/ (so tests 03-09 appear in the index)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

SCRIPTS_DIR = Path(__file__).parent.parent
REPO_ROOT = SCRIPTS_DIR.parent


# ── Time helpers ──────────────────────────────────────────────────────────────


def now_ms() -> int:
    """Current UTC epoch time in milliseconds."""
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def elapsed_human(start_ms: int, end_ms: int | None = None) -> str:
    if end_ms is None:
        end_ms = now_ms()
    s = (end_ms - start_ms) // 1000
    return f"{s // 60}m{s % 60}s"


# ── Argument parsing ──────────────────────────────────────────────────────────


def standard_args(description: str = "") -> argparse.ArgumentParser:
    """
    Return an ArgumentParser with the standard set of benchmark arguments.

    Each test script calls this, then adds any test-specific args before
    calling parser.parse_args().

    Standard args:
      --cluster-name   ROSA cluster name (required)
      --cluster-type   classic | hcp (required)
      --run-id         benchmark run ID (optional; skips checkpoint/event recording if absent)
      --kubeconfig     path to kubeconfig file (defaults to KUBECONFIG env or tmp/kubeconfig.<name>.yaml)
      --timeout        global timeout in seconds (default 1800)
      --dry-run        print actions without executing oc commands
    """
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--cluster-name", required=True, help="ROSA cluster name")
    p.add_argument(
        "--cluster-type",
        required=True,
        choices=["classic", "hcp", "hcp-autonode"],
        help="Cluster topology",
    )
    p.add_argument(
        "--run-id",
        default="",
        help="Benchmark run ID for checkpoint and event recording (omit to skip)",
    )
    p.add_argument(
        "--kubeconfig",
        default="",
        help="Path to kubeconfig file (defaults to KUBECONFIG env or tmp/kubeconfig.<cluster-name>.yaml)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Global timeout in seconds (default: 1800)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without executing oc commands",
    )
    return p


def resolve_kubeconfig(args: argparse.Namespace) -> str | None:
    """
    Return the kubeconfig path to use, in priority order:
    1. --kubeconfig flag
    2. KUBECONFIG env var
    3. tmp/kubeconfig.<cluster-name>.yaml under repo root
    Returns None to let oc use its own default search.
    """
    if args.kubeconfig:
        return args.kubeconfig
    if os.environ.get("KUBECONFIG"):
        return os.environ["KUBECONFIG"]
    candidate = REPO_ROOT / "tmp" / f"kubeconfig.{args.cluster_name}.yaml"
    if candidate.exists():
        return str(candidate)
    return None


def resolve_run_id_from_cluster_json(
    cluster_type: str,
    cluster_name: str | None = None,
) -> str:
    """
    Read ``run_id`` from ``tmp/cluster.<cluster_type>.json`` when the harness
    wrote cluster state (e.g. after ``make create-classic`` / ``create-hcp``).

    If ``cluster_name`` is set and the JSON has a different ``cluster_name``,
    logs a warning but still returns the file's ``run_id``.

    Returns ``''`` if the file is missing or has no ``run_id``.
    """
    path = REPO_ROOT / "tmp" / f"cluster.{cluster_type}.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    json_name = data.get("cluster_name")
    if cluster_name and json_name and str(json_name) != str(cluster_name):
        print(
            f"[bench] WARNING: {path.name} has cluster_name={json_name!r} but "
            f"--cluster-name={cluster_name!r}; using run_id from file anyway.",
            file=sys.stderr,
        )
    rid = data.get("run_id")
    return str(rid).strip() if rid else ""


# ── Checkpoint management ─────────────────────────────────────────────────────


def checkpoint_start(run_id: str, test_id: str) -> None:
    """Mark a test as in_progress in the checkpoint file."""
    if not run_id:
        return
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "checkpoint.py"), "start",
         "--run-id", run_id, "--test", test_id],
        check=True,
    )


def checkpoint_complete(run_id: str, test_id: str) -> None:
    """Mark a test as completed in the checkpoint file."""
    if not run_id:
        return
    subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "checkpoint.py"), "complete",
         "--run-id", run_id, "--test", test_id],
        check=True,
    )


def checkpoint_fail(run_id: str, test_id: str, reason: str = "") -> None:
    """Mark a test as failed in the checkpoint file."""
    if not run_id:
        return
    cmd = [sys.executable, str(SCRIPTS_DIR / "checkpoint.py"), "fail",
           "--run-id", run_id, "--test", test_id]
    if reason:
        cmd += ["--reason", reason]
    subprocess.run(cmd, check=False)  # best-effort — don't raise during error handling


# ── Milestone recording ───────────────────────────────────────────────────────


def record_milestone(
    label: str,
    start_ms: int,
    end_ms: int,
    *,
    run_id: str,
    cluster_type: str,
    cluster_name: str,
    meta: dict[str, str] | None = None,
) -> None:
    """
    Append a timing event to the run's events.jsonl via record-event.py.

    Prints a human-readable confirmation to stderr.
    No-op if run_id is empty.
    """
    if not run_id:
        print(
            f"[milestone] {label}: {elapsed_human(start_ms, end_ms)} (no run-id — not persisted)",
            file=sys.stderr,
        )
        return

    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "record-event.py"),
        "record",
        "--run-id", run_id,
        "--label", label,
        "--start-ms", str(start_ms),
        "--end-ms", str(end_ms),
        "--cluster-type", cluster_type,
        "--cluster-name", cluster_name,
    ]
    if meta:
        cmd += ["--meta"] + [f"{k}={v}" for k, v in meta.items()]

    subprocess.run(cmd, check=True)


# ── Result output ─────────────────────────────────────────────────────────────


class BenchmarkResult:
    """
    Collects milestone timings and emits a structured JSON summary.

    Usage::

        result = BenchmarkResult(run_id=args.run_id, test_id="03-autoscale-up")
        result.milestone("workload_applied", start_ms, end_ms)
        ...
        result.print_summary()  # writes JSON to stdout
    """

    def __init__(self, *, run_id: str, test_id: str, cluster_type: str, cluster_name: str) -> None:
        self.run_id = run_id
        self.test_id = test_id
        self.cluster_type = cluster_type
        self.cluster_name = cluster_name
        self.milestones: list[dict] = []  # type: ignore[type-arg]
        self.status = "ok"
        self.error: str = ""
        self.extra: dict = {}  # type: ignore[type-arg]

    def milestone(
        self,
        label: str,
        start_ms: int,
        end_ms: int,
        *,
        meta: dict[str, str] | None = None,
    ) -> None:
        """Record a timing milestone and persist it to events.jsonl."""
        full_label = f"{self.test_id}.{label}"
        elapsed = end_ms - start_ms
        entry = {
            "label": full_label,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "elapsed_ms": elapsed,
            "elapsed_human": elapsed_human(start_ms, end_ms),
        }
        if meta:
            entry["meta"] = meta
        self.milestones.append(entry)

        record_milestone(
            full_label,
            start_ms,
            end_ms,
            run_id=self.run_id,
            cluster_type=self.cluster_type,
            cluster_name=self.cluster_name,
            meta=meta,
        )

    def fail(self, reason: str) -> None:
        self.status = "failed"
        self.error = reason
        checkpoint_fail(self.run_id, self.test_id, reason)

    def print_summary(self) -> None:
        """Write a JSON summary to stdout. Skills read this to build the Canvas."""
        summary = {
            "test_id": self.test_id,
            "run_id": self.run_id,
            "cluster_type": self.cluster_type,
            "cluster_name": self.cluster_name,
            "status": self.status,
            "milestones": self.milestones,
        }
        if self.error:
            summary["error"] = self.error
        if self.extra:
            summary["extra"] = self.extra
        print(json.dumps(summary, indent=2))

    def finish(self) -> None:
        """
        Complete a test run: write JSON summary to stdout and HTML report to reports/.

        Call this instead of print_summary() at the end of each test script so
        that both deliverables are produced together. The HTML report uses the
        same RUN_ID as the cluster-install report, making all test results linkable.
        """
        self.print_summary()
        write_html_report(self)


# ── Fatal error handling ──────────────────────────────────────────────────────


def fatal(
    msg: str,
    *,
    run_id: str,
    test_id: str,
    result: BenchmarkResult | None = None,
) -> NoReturn:
    """
    Print an error, mark the checkpoint as failed, emit a partial summary, and exit 1.

    Call this instead of sys.exit() anywhere an unrecoverable error occurs so that
    the events.jsonl already written by result.milestone() calls are preserved.
    """
    print(f"[FATAL] {msg}", file=sys.stderr)
    checkpoint_fail(run_id, test_id, reason=msg)
    if result is not None:
        result.status = "failed"
        result.error = msg
        result.print_summary()
    sys.exit(1)


# ── SIGINT / cleanup ──────────────────────────────────────────────────────────


def handle_sigint(
    cleanup_fn: Callable[[], None],
    *,
    run_id: str,
    test_id: str,
    result: BenchmarkResult | None = None,
) -> None:
    """
    Register a SIGINT handler that:
    1. Calls cleanup_fn() to remove deployed workloads
    2. Marks the checkpoint as failed
    3. Emits a partial JSON summary
    4. Exits with code 130

    cleanup_fn should be idempotent and must not raise.
    """

    def _handler(signum: int, frame: object) -> None:
        print("\n[SIGINT] Interrupted — running cleanup ...", file=sys.stderr)
        try:
            cleanup_fn()
        except Exception as exc:
            print(f"[SIGINT] cleanup error (ignored): {exc}", file=sys.stderr)
        checkpoint_fail(run_id, test_id, reason="interrupted by SIGINT")
        if result is not None:
            result.status = "partial"
            result.error = "interrupted"
            result.print_summary()
        sys.exit(130)

    signal.signal(signal.SIGINT, _handler)


# ── Pre-flight checks ─────────────────────────────────────────────────────────


def verify_oc_login(kubeconfig: str | None = None) -> str:
    """
    Verify that `oc whoami` succeeds. Returns the current user.
    Raises SystemExit if not logged in.
    """
    from scripts.lib.oc import OcError, run_oc

    try:
        user = run_oc(["whoami"], json_output=False, kubeconfig=kubeconfig).strip()
        print(f"[preflight] oc logged in as: {user}", file=sys.stderr)
        return user
    except OcError as exc:
        print(
            f"[preflight] FAIL: `oc whoami` failed — are you logged in?\n{exc}",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Cluster state file ────────────────────────────────────────────────────────


def read_cluster_state(cluster_type: str) -> dict[str, str]:
    """
    Read tmp/cluster.{cluster_type}.json and return its contents as a dict.

    Returns an empty dict if the file does not exist (cluster not yet created
    or already destroyed). The state file is written by clusters/common.sh
    write_cluster_state during `make create-*` and cleared on `make destroy-*`.

    Typical keys: cluster_name, cluster_type, run_id, api_url, username,
    password, region, rosa_version, created_at, kubeconfig.
    """
    state_path = REPO_ROOT / "tmp" / f"cluster.{cluster_type}.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def resolve_run_id(cluster_name: str, cluster_type: str) -> str | None:
    """
    Return the run_id for the active cluster of the given type.

    Reads tmp/cluster.{cluster_type}.json (written by make create-*).
    Returns None if the state file is absent, does not match cluster_name,
    or has no run_id field — caller should prompt the user to supply --run-id.
    """
    state = read_cluster_state(cluster_type)
    if state.get("cluster_name") == cluster_name:
        return state.get("run_id") or None
    return None


# ── HTML report output ────────────────────────────────────────────────────────

# Map test IDs to human-readable names for report titles.
_TEST_TITLES: dict[str, str] = {
    "02-machine-pool": "Machine pool provisioning",
    "03-autoscale-up": "Cluster Autoscaler scale-up",
    "04-autoscale-down": "Cluster Autoscaler scale-down",
    "05-unschedulable": "Unschedulable oversize workload",
    "06-hpa": "Horizontal Pod Autoscaler",
    "07-vpa-advise": "VPA advise-only recommendations",
    "08-hpa-triggers-cas": "HPA triggers Cluster Autoscaler",
    "09-overprovisioning": "Overprovisioning with pause pods",
    "10-autonode-scale": "AutoNode (Karpenter) scale-up and consolidation",
    "11-planned-surge": "Planned surge — proactive scale-up",
    "12-sudden-spike": "Sudden spike — reactive scale-up (degradation window)",
    "13-parallel-nodes": "Multi-node parallel provisioning",
}

_HTML_STYLE = """
    :root {
      --bg: #0f1419;
      --surface: #1a2332;
      --border: #2d3a4d;
      --text: #e6edf3;
      --muted: #8b9cb3;
      --accent: #58a6ff;
      --warning: #d4a72c;
      --ok: #3fb950;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      font-size: 15px;
    }
    main { max-width: 920px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
    header.doc {
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.25rem;
      margin-bottom: 1.75rem;
    }
    h1 { font-size: 1.35rem; font-weight: 600; margin: 0 0 0.35rem; letter-spacing: -0.02em; }
    .subtitle { color: var(--muted); font-size: 0.95rem; margin: 0; }
    dl.meta {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 0.35rem 1.25rem;
      margin: 1.25rem 0 0;
      font-size: 0.9rem;
    }
    dl.meta dt { color: var(--muted); font-weight: 500; }
    dl.meta dd { margin: 0; }
    h2 {
      font-size: 1.05rem;
      font-weight: 600;
      margin: 2rem 0 0.75rem;
      color: var(--accent);
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
    }
    .stat {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.9rem 1rem;
    }
    .stat .label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
    .stat .value { font-size: 1.4rem; font-weight: 700; margin-top: 0.2rem; font-variant-numeric: tabular-nums; }
    table.timeline {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      margin-top: 0.5rem;
    }
    table.timeline th, table.timeline td {
      text-align: left;
      padding: 0.45rem 0.6rem;
      border-bottom: 1px solid var(--border);
    }
    table.timeline th { color: var(--muted); font-weight: 500; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .badge-ok { color: var(--ok); }
    .badge-warn { color: var(--warning); }
    .badge-fail { color: #f85149; }
    pre.json-extra { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem 1rem; font-size: 0.82rem; overflow-x: auto; white-space: pre-wrap; }
    footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: 0.82rem; color: var(--muted); }
    a { color: var(--accent); }
"""


def write_html_report(result: BenchmarkResult, *, reports_dir: Path | None = None) -> Path | None:
    """
    Write an HTML summary report to reports/<RUN_ID>-NN-<type>-<test-name>.html.

    Matches the visual style of the test-01 install reports so all benchmark
    output looks consistent. Returns the path written, or None if skipped
    (no run_id, or reports_dir does not exist and cannot be created).

    This is called automatically by BenchmarkResult.finish() — test scripts
    do not need to call it directly.
    """
    import json as _json

    if not result.run_id:
        return None

    if reports_dir is None:
        reports_dir = REPO_ROOT / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[report] WARNING: cannot create reports dir: {exc}", file=sys.stderr)
        return None

    test_id = result.test_id              # e.g. "06-hpa"
    test_num = test_id.split("-")[0]      # e.g. "06"
    cluster_type = result.cluster_type    # "classic" | "hcp"
    test_slug = test_id[len(test_num) + 1:]  # e.g. "hpa"
    title_suffix = _TEST_TITLES.get(test_id, test_id)

    filename = f"{result.run_id}-{test_num}-{cluster_type}-{test_slug}.html"
    out_path = reports_dir / filename

    generated = ms_to_iso(now_ms())
    status_badge = {
        "ok": '<span class="badge-ok">✓ ok</span>',
        "partial": '<span class="badge-warn">⚠ partial</span>',
        "failed": '<span class="badge-fail">✗ failed</span>',
    }.get(result.status, result.status)

    # Build milestone rows
    milestone_rows = ""
    for m in result.milestones:
        label = m.get("label", "")
        elapsed = m.get("elapsed_human", "")
        elapsed_ms = m.get("elapsed_ms", 0)
        milestone_rows += f"""
          <tr>
            <td>{label}</td>
            <td style="font-variant-numeric:tabular-nums">{elapsed}</td>
            <td style="font-variant-numeric:tabular-nums;color:var(--muted)">{elapsed_ms:,} ms</td>
          </tr>"""

    # Key stats: total elapsed (last milestone end − first milestone start)
    total_elapsed = ""
    if result.milestones:
        first_start = result.milestones[0]["start_ms"]
        last_end = result.milestones[-1]["end_ms"]
        total_elapsed = elapsed_human(first_start, last_end)

    # Install report link (test 01 for same run)
    install_report = f"{result.run_id}-01-{cluster_type}-cluster-install.html"
    install_link = (
        f'<a href="{install_report}">{install_report}</a>'
        if (reports_dir / install_report).exists()
        else f'<code>{install_report}</code> (not yet written)'
    )

    extra_json = _json.dumps(result.extra, indent=2) if result.extra else ""
    error_section = (
        f'<section><h2>Error</h2><pre class="json-extra">{result.error}</pre></section>'
        if result.error
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Benchmark {test_num} — {title_suffix} ({cluster_type})</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <main>
    <header class="doc">
      <h1>Benchmark {test_num} — {title_suffix}</h1>
      <p class="subtitle">ROSA {cluster_type.upper()} · {result.cluster_name}</p>
      <dl class="meta">
        <dt>Run ID</dt>  <dd><code>{result.run_id}</code></dd>
        <dt>Cluster name</dt>  <dd><code>{result.cluster_name}</code></dd>
        <dt>Cluster type</dt>  <dd>{cluster_type}</dd>
        <dt>Status</dt>  <dd>{status_badge}</dd>
        <dt>Total elapsed</dt>  <dd>{total_elapsed or '—'}</dd>
        <dt>Report generated</dt>  <dd><code>{generated}</code></dd>
        <dt>Cluster install report</dt>  <dd>{install_link}</dd>
      </dl>
    </header>

    <section>
      <h2>Milestones</h2>
      <table class="timeline">
        <thead>
          <tr>
            <th>Event</th>
            <th>Elapsed</th>
            <th>Elapsed (ms)</th>
          </tr>
        </thead>
        <tbody>
          {milestone_rows or '<tr><td colspan="3" style="color:var(--muted)">No milestones recorded.</td></tr>'}
        </tbody>
      </table>
    </section>

    {error_section}

    {'<section><h2>Extra data</h2><pre class="json-extra">' + extra_json + '</pre></section>' if extra_json else ''}

    <footer>
      Run ID: <code>{result.run_id}</code> ·
      Generated: <code>{generated}</code> ·
      Regenerate index: <code>python3 scripts/update-reports-index.py</code>
    </footer>
  </main>
</body>
</html>
"""

    out_path.write_text(html, encoding="utf-8")
    print(f"[report] Written: {out_path}", file=sys.stderr)
    return out_path


# ── Node telemetry collection ─────────────────────────────────────────────────


def collect_node_telemetry(
    node_name: str,
    *,
    prefix: str,
    since_ms: int,
    run_id: str,
    cluster_type: str,
    cluster_name: str,
    kubeconfig: str | None = None,
    region: str | None = None,
) -> None:
    """
    Fire-and-forget post-factum telemetry for a newly Ready node.

    Calls scripts/collect-node-telemetry.py which collects:
      - CloudTrail RunInstances timestamp
      - Ignition/kubelet systemd journal milestones (oc adm node-logs)
      - EC2 status-check timeline (CloudWatch)
      - Serial console output (saved to raw/)
      - systemd-analyze + blame + cloud-init log (oc debug, ~60-150s)

    Non-fatal: all errors are printed as warnings, never raised.
    Typically called right after wait_for_new_ready_node() returns.
    """
    if not run_id:
        return

    script = SCRIPTS_DIR / "collect-node-telemetry.py"
    effective_region = region or os.environ.get("AWS_REGION", "us-east-1")
    raw_dir = REPO_ROOT / "results" / run_id / "raw"

    cmd = [
        sys.executable, str(script),
        "--nodes", node_name,
        "--cluster", cluster_name,
        "--run-id", run_id,
        "--region", effective_region,
        "--raw-dir", str(raw_dir),
        "--prefix", prefix,
        "--cluster-type", cluster_type,
        "--cluster-name", cluster_name,
        "--since-ms", str(since_ms),
    ]
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]

    try:
        subprocess.run(cmd, check=False, timeout=360)
    except subprocess.TimeoutExpired:
        print(
            f"[bench] WARNING: collect_node_telemetry timed out for {node_name}.",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"[bench] WARNING: collect_node_telemetry failed for {node_name}: {exc}",
            file=sys.stderr,
        )
