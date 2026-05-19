#!/usr/bin/env python3
"""
scripts/generate-comparison-report.py

Generate a side-by-side HTML comparison report between a Classic (CAS) run
and an HCP AutoNode (Karpenter) run.

Reads results/<run-id>/events.jsonl for both runs and produces a dark-theme
HTML report at reports/<timestamp>-comparison.html with six panels:

  1. Cluster install
  2. Cold-start node provisioning (workload → pods Running)
  3. HPA response (on existing capacity)
  4. HPA → autoscaler cascade (cluster full → new node → pods)
  5. Scale-down
  6. Overprovisioned HPA (balloon pods)

Usage:
  python3 scripts/generate-comparison-report.py \\
      --classic-run-id 20260508T025316-classic \\
      --autonode-run-id 20260508T031735-hcp-autonode \\
      [--output reports/]

  # Auto-detect most recent runs of each type:
  python3 scripts/generate-comparison-report.py --auto
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
RESULTS_DIR = REPO_ROOT / "results"


# ── Milestone extraction ──────────────────────────────────────────────────────


def load_milestones(run_id: str) -> dict[str, int]:
    """Read results/<run-id>/events.jsonl and return {label: elapsed_ms}."""
    events_path = RESULTS_DIR / run_id / "events.jsonl"
    if not events_path.exists():
        print(f"[warn] events.jsonl not found for run {run_id!r}", file=sys.stderr)
        return {}
    milestones: dict[str, int] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            label = event.get("label", "")
            elapsed = event.get("elapsed_ms")
            if label and elapsed is not None:
                milestones[label] = int(elapsed)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] could not read events.jsonl for {run_id!r}: {exc}", file=sys.stderr)
    return milestones


def _ms(milestones: dict[str, int], *keys: str) -> int | None:
    """Return the first matching key's value, or None."""
    for key in keys:
        if key in milestones:
            return milestones[key]
    return None


def _fmt(ms: int | None) -> str:
    if ms is None:
        return "—"
    s = ms // 1000
    m, sec = divmod(s, 60)
    return f"{m}m {sec:02d}s"


def _delta_pct(cas_ms: int | None, kp_ms: int | None) -> str:
    if cas_ms is None or kp_ms is None or kp_ms == 0:
        return "—"
    ratio = cas_ms / kp_ms
    pct = round((ratio - 1) * 100)
    if ratio > 1:
        return f"Karpenter {ratio:.1f}× faster (+{pct}%)"
    elif ratio < 1:
        ratio_inv = round(1 / ratio, 1)
        return f"CAS {ratio_inv}× faster"
    return "equal"


def _tone(cas_ms: int | None, kp_ms: int | None) -> str:
    """Return CSS class based on which is faster."""
    if cas_ms is None or kp_ms is None:
        return ""
    if kp_ms < cas_ms:
        return "kp-faster"
    if cas_ms < kp_ms:
        return "cas-faster"
    return ""


# ── Scenario definitions ──────────────────────────────────────────────────────


def extract_metrics(
    classic_ms: dict[str, int],
    autonode_ms: dict[str, int],
) -> list[dict]:
    """
    Return a list of scenario dicts for the HTML template.

    Each dict has: title, description, cas_label, kp_label,
    cas_ms, kp_ms, cas_fmt, kp_fmt, delta, tone, note.
    """
    scenarios = []

    def row(
        title: str,
        description: str,
        cas_keys: list[str],
        kp_keys: list[str],
        note: str = "",
    ) -> dict:
        cas = _ms(classic_ms, *cas_keys)
        kp = _ms(autonode_ms, *kp_keys)
        return {
            "title": title,
            "description": description,
            "cas_fmt": _fmt(cas),
            "kp_fmt": _fmt(kp),
            "delta": _delta_pct(cas, kp),
            "tone": _tone(cas, kp),
            "note": note,
            "cas_ms": cas,
            "kp_ms": kp,
        }

    scenarios.append(row(
        "Cluster install",
        "Total time from provisioning start to ClusterOperators Available",
        [
            "01-classic-cluster-install.pending_to_cluster_operators_available",
            "01-classic-cluster-install.ocm_accepted_to_cluster_operators_available",
            "classic.total",
        ],
        [
            "01-hcp-cluster-install.pending_to_cluster_operators_available",
            "01-hcp-autonode-cluster-install.pending_to_cluster_operators_available",
            # HCP AutoNode create.sh records hcp.operators_ready (ClusterOperators Available)
            # and hcp.total (includes AutoNode IAM + enable steps ~12min extra)
            "hcp.operators_ready",
            "hcp.total",
        ],
        note="Different platforms — HCP hosts the control plane on Red Hat infra. "
             "HCP time shown is to ClusterOperators Available (hcp.operators_ready); "
             "hcp.total includes AutoNode IAM setup (~12min extra).",
    ))

    scenarios.append(row(
        "Cold-start node provision",
        "Unschedulable workload applied → FailedScheduling → scheduler decision → node Ready → pods Ready (serving)",
        [
            "03-autoscale-up.workload_applied_to_pods_ready",
            "03-autoscale-up.workload_applied_to_pods_running",
            "03-autoscale-up.workload_applied_to_pods_running_partial",
        ],
        [
            "10-autonode-scale.initial.pending_to_pods_ready",
            "10-autonode-scale.initial.pending_to_pods_running",
        ],
        note="Test 10 uses --trigger-mode=pause-pods for parity with Test 03 FailedScheduling chain. "
             "Prefers pods_ready (readiness probe passed) over pods_running.",
    ))

    scenarios.append(row(
        "Scheduler decision latency",
        "FailedScheduling → CAS TriggeredScaleUp/ScaledUpGroup (CAS) or NodeClaim created (Karpenter)",
        [
            "03-autoscale-up.failed_scheduling_to_cas_triggered",
        ],
        [
            "10-autonode-scale.initial.failed_scheduling_to_nodeclaim",
        ],
        note="Sub-second for Karpenter; CAS polls on a loop (~10–30 s typical)",
    ))

    scenarios.append(row(
        "HPA response (on existing capacity)",
        "CPU metric breach → HPA desiredReplicas change → all new pods Ready (serving traffic)",
        [
            "06-hpa.metric_breach_to_pods_ready",
            "06-hpa.metric_breach_to_pods_running",
        ],
        [
            "06-hpa.metric_breach_to_pods_ready",
            "06-hpa.metric_breach_to_pods_running",
        ],
        note="Same script, same flow — HPA/metrics-server latency dominates; scheduler has no role. "
             "Prefers pods_ready (readiness probe passed) over pods_running.",
    ))

    scenarios.append(row(
        "HPA → autoscaler cascade (e2e)",
        "HPA trigger → cluster full → scheduler decision → new node Ready → all pods Ready (serving)",
        [
            "08-hpa-triggers-cas.hpa_trigger_to_all_ready",
            "08-hpa-triggers-cas.hpa_trigger_to_all_running",
        ],
        [
            "08-hpa-triggers-cas.hpa_trigger_to_all_ready",
            "08-hpa-triggers-cas.hpa_trigger_to_all_running",
        ],
        note="Same script; Test 08 uses NodeClaim watch for Karpenter, CAS event watch for Classic. "
             "Prefers pods_ready (readiness probe passed) over pods_running.",
    ))

    scenarios.append(row(
        "Scale-down",
        "Workload removed → autoscaler consolidates / removes idle node",
        [
            "04-autoscale-down.workload_removed_to_stable",
        ],
        [
            # Karpenter consolidation milestones recorded by test 10
            "10-autonode-scale.rollback_1.scale_to_node_removed",
            "10-autonode-scale.rollback_3.scale_to_node_removed",
            "10-autonode-scale.rollback_1.scale_to_consolidated",
            "10-autonode-scale.rollback_3.scale_to_consolidated",
        ],
        note="CAS: scale-down-delay-after-add 10m default (dominant factor). "
             "Karpenter: consolidateAfter 30s — acts almost immediately once node is idle.",
    ))

    scenarios.append(row(
        "Overprovisioned HPA (balloon pods)",
        "HPA fires on saturated cluster with pre-reserved headroom → pods Ready (serving) via preemption",
        [
            "09-overprovisioning.hpa_trigger_to_pods_ready",
            "09-overprovisioning.hpa_trigger_to_pods_running",
        ],
        [
            "09b-karpenter-overprovisioning.hpa_trigger_to_pods_ready",
            "09b-karpenter-overprovisioning.hpa_trigger_to_pods_running",
        ],
        note="Shows whether Karpenter's faster provisioning reduces the benefit of balloon pods. "
             "Prefers pods_ready (readiness probe passed) over pods_running.",
    ))

    return scenarios


# ── HTML template ─────────────────────────────────────────────────────────────


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ROSA CAS vs AutoNode Comparison — {timestamp}</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d27;
      --border: #2a2d3a;
      --text: #e2e4ed;
      --muted: #8b8fa8;
      --accent: #5b8dee;
      --success: #3ecf8e;
      --warning: #f0a500;
      --danger: #e5484d;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px;
      line-height: 1.6;
      padding: 40px 24px;
    }}
    .container {{ max-width: 1000px; margin: 0 auto; }}
    h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
    h2 {{ font-size: 16px; font-weight: 600; margin: 32px 0 12px; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-bottom: 32px; }}
    .tag {{ color: var(--accent); }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 32px;
    }}
    .stat {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .stat-value {{ font-size: 20px; font-weight: 700; }}
    .stat-value.success {{ color: var(--success); }}
    .stat-value.accent {{ color: var(--accent); }}
    .stat-label {{ font-size: 11px; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
    th {{
      text-align: left; font-size: 11px; font-weight: 600;
      color: var(--muted); text-transform: uppercase;
      letter-spacing: 0.06em; padding: 8px 12px;
      border-bottom: 1px solid var(--border);
    }}
    td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    td.kp-faster {{ color: var(--success); font-weight: 600; }}
    td.cas-faster {{ color: var(--warning); font-weight: 600; }}
    .note {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .scenario-title {{ font-weight: 600; }}
    .scenario-desc {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
    .divider {{ border: none; border-top: 1px solid var(--border); margin: 28px 0; }}
    .missing {{ color: var(--muted); font-style: italic; }}
    .callout {{
      background: var(--surface);
      border-left: 3px solid var(--warning);
      border-radius: 4px;
      padding: 12px 16px;
      margin-bottom: 24px;
      font-size: 13px;
    }}
    footer {{ margin-top: 40px; color: var(--muted); font-size: 11px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
<div class="container">

  <h1>ROSA Classic CAS vs HCP AutoNode — Side-by-Side Comparison</h1>
  <p class="meta">
    Classic run: <span class="tag">{classic_run_id}</span> &nbsp;·&nbsp;
    AutoNode run: <span class="tag">{autonode_run_id}</span> &nbsp;·&nbsp;
    Generated: <span class="tag">{timestamp}</span>
  </p>

  <div class="callout">
    Rows marked with "—" indicate the milestone was not recorded in that run's events.jsonl.
    This can mean the test was not run, the script version pre-dates the milestone, or the run
    was partial. Re-run the affected test with the updated scripts to populate missing metrics.
  </div>

  <!-- Summary stats -->
  <h2>Summary</h2>
  <div class="stats-grid">
    <div class="stat">
      <div class="stat-value accent">{kp_wins}</div>
      <div class="stat-label">Scenarios where Karpenter is faster</div>
    </div>
    <div class="stat">
      <div class="stat-value">{cas_wins}</div>
      <div class="stat-label">Scenarios where CAS is faster</div>
    </div>
    <div class="stat">
      <div class="stat-value">{missing}</div>
      <div class="stat-label">Scenarios with missing data</div>
    </div>
    <div class="stat">
      <div class="stat-value success">{best_delta}</div>
      <div class="stat-label">Best Karpenter speedup observed</div>
    </div>
  </div>

  <hr class="divider" />

  <!-- Main comparison table -->
  <h2>Scenario Comparison</h2>
  <table>
    <thead>
      <tr>
        <th style="width:26%">Scenario</th>
        <th style="width:14%">Classic CAS</th>
        <th style="width:14%">HCP AutoNode</th>
        <th style="width:20%">Result</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>

  <hr class="divider" />

  <!-- Scale-down policy note -->
  <h2>Scale-Down Policy Context</h2>
  <table>
    <thead>
      <tr>
        <th>Parameter</th>
        <th>Classic CAS</th>
        <th>HCP AutoNode (Karpenter)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Idle node detection</td>
        <td>scale-down-unneeded-time: 10m (default)</td>
        <td>consolidateAfter: 30s</td>
      </tr>
      <tr>
        <td>Post-scale-up cooldown</td>
        <td>scale-down-delay-after-add: 10m (default)</td>
        <td>No equivalent — Karpenter acts immediately when node is idle</td>
      </tr>
      <tr>
        <td>Policy location</td>
        <td>cluster-autoscaler Deployment flags</td>
        <td>NodePool spec.disruption.consolidateAfter</td>
      </tr>
      <tr>
        <td>Note</td>
        <td colspan="2">The scale-down delta is almost entirely policy, not architecture.
          Tuning CAS to 30s delays would produce similar results. Both are operator-configurable.</td>
      </tr>
    </tbody>
  </table>

  <hr class="divider" />

  <footer>
    Generated by scripts/generate-comparison-report.py &nbsp;·&nbsp;
    Classic: {classic_run_id} &nbsp;·&nbsp;
    AutoNode: {autonode_run_id} &nbsp;·&nbsp;
    {timestamp}
    &nbsp;·&nbsp; <a href="index.html">Back to index</a>
  </footer>

</div>
</body>
</html>
"""


def _render_row(s: dict) -> str:
    cas_td = f'<td class="{s["tone"]}">{s["cas_fmt"]}</td>' if s["tone"] and s["cas_ms"] and s["cas_ms"] > (s["kp_ms"] or 0) else f"<td>{s['cas_fmt']}</td>"
    kp_td = f'<td class="{s["tone"]}">{s["kp_fmt"]}</td>' if s["tone"] and s["kp_ms"] and s["kp_ms"] < (s["cas_ms"] or 0) else f"<td>{s['kp_fmt']}</td>"
    delta_td = f'<td class="{s["tone"]}">{s["delta"]}</td>' if s["tone"] else f"<td>{s['delta']}</td>"
    note_html = f'<div class="note">{s["note"]}</div>' if s["note"] else ""
    return (
        "      <tr>\n"
        f'        <td><div class="scenario-title">{s["title"]}</div>'
        f'<div class="scenario-desc">{s["description"]}</div></td>\n'
        f"        {cas_td}\n"
        f"        {kp_td}\n"
        f"        {delta_td}\n"
        f"        <td>{note_html}</td>\n"
        "      </tr>"
    )


def generate_html(
    classic_run_id: str,
    autonode_run_id: str,
    scenarios: list[dict],
    timestamp: str,
) -> str:
    rows = "\n".join(_render_row(s) for s in scenarios)

    kp_wins = sum(1 for s in scenarios if s["kp_ms"] and s["cas_ms"] and s["kp_ms"] < s["cas_ms"])
    cas_wins = sum(1 for s in scenarios if s["kp_ms"] and s["cas_ms"] and s["cas_ms"] < s["kp_ms"])
    missing = sum(1 for s in scenarios if not s["kp_ms"] or not s["cas_ms"])

    best_ratio = 1.0
    for s in scenarios:
        if s["cas_ms"] and s["kp_ms"] and s["kp_ms"] > 0:
            r = s["cas_ms"] / s["kp_ms"]
            if r > best_ratio:
                best_ratio = r
    best_delta = f"{best_ratio:.1f}×" if best_ratio > 1 else "—"

    return _HTML_TEMPLATE.format(
        classic_run_id=classic_run_id,
        autonode_run_id=autonode_run_id,
        timestamp=timestamp,
        rows=rows,
        kp_wins=kp_wins,
        cas_wins=cas_wins,
        missing=missing,
        best_delta=best_delta,
    )


# ── Auto-detect runs ──────────────────────────────────────────────────────────


def _latest_run_of_type(suffix: str) -> str | None:
    """Return the most recently modified run ID directory matching *suffix*."""
    candidates = [
        d for d in sorted(RESULTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if d.is_dir() and d.name.endswith(suffix)
    ]
    return candidates[0].name if candidates else None


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate CAS vs AutoNode comparison report."
    )
    parser.add_argument("--classic-run-id", help="Classic CAS run ID (e.g. 20260508T025316-classic)")
    parser.add_argument("--autonode-run-id", help="HCP AutoNode run ID (e.g. 20260508T031735-hcp-autonode)")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect the most recent classic and hcp-autonode run IDs.",
    )
    parser.add_argument(
        "--output",
        default=str(REPORTS_DIR),
        help=f"Output directory (default: {REPORTS_DIR})",
    )
    args = parser.parse_args()

    classic_run_id = args.classic_run_id
    autonode_run_id = args.autonode_run_id

    if args.auto:
        classic_run_id = classic_run_id or _latest_run_of_type("-classic")
        autonode_run_id = autonode_run_id or _latest_run_of_type("-hcp-autonode")

    if not classic_run_id or not autonode_run_id:
        parser.error(
            "Provide --classic-run-id and --autonode-run-id, or use --auto to detect them.\n"
            f"Available run IDs: {[d.name for d in RESULTS_DIR.iterdir() if d.is_dir()]}"
        )

    print(f"[compare] Classic run:  {classic_run_id}", file=sys.stderr)
    print(f"[compare] AutoNode run: {autonode_run_id}", file=sys.stderr)

    classic_ms = load_milestones(classic_run_id)
    autonode_ms = load_milestones(autonode_run_id)

    print(
        f"[compare] Loaded {len(classic_ms)} classic milestones, "
        f"{len(autonode_ms)} autonode milestones.",
        file=sys.stderr,
    )

    scenarios = extract_metrics(classic_ms, autonode_ms)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    html = generate_html(classic_run_id, autonode_run_id, scenarios, timestamp)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-comparison.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"[compare] Written: {out_file}", file=sys.stderr)
    print(str(out_file))


if __name__ == "__main__":
    main()
