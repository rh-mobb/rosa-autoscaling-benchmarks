#!/usr/bin/env python3
"""
Autoscaling Advisor — Phase B standalone agent.

Usage:
  python3 agent.py [options]

Options:
  --cluster-type  classic | hcp | hcp-autonode  (default: classic)
  --kubeconfig    path to kubeconfig (default: KUBECONFIG env or tmp/kubeconfig.*.yaml)
  --namespace     scope to a specific namespace (default: cluster-wide)
  --workload      scope to a specific deployment name (default: all)
  --output        json | html | both            (default: both)
  --out-dir       output directory              (default: reports/advisor)
  --run-id        benchmark run ID for event.jsonl lookup (optional)
  --results-dir   results/ directory for events.jsonl   (default: results)
  --quiet         suppress progress output
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Allow running from the advisor/ directory or from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.phases.topology import discover as phase1_discover
from advisor.phases.observation import observe as phase2_observe
from advisor.phases.reasoning import reason as phase3_reason
from advisor.output import canvas as canvas_out
from advisor.output import json_report as json_out
from advisor.lib.events_jsonl import load_benchmark_latencies


def _resolve_kubeconfig(cluster_type: str, kubeconfig_arg: Optional[str]) -> Optional[str]:
    if kubeconfig_arg:
        return kubeconfig_arg
    if os.environ.get("KUBECONFIG"):
        return os.environ["KUBECONFIG"]
    # Try harness state files
    patterns = [
        f"tmp/kubeconfig.{cluster_type}-*.yaml",
        f"tmp/kubeconfig.*.yaml",
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


def _print_phase(n: int, title: str, quiet: bool) -> None:
    if not quiet:
        print(f"\n{'='*60}")
        print(f"  Phase {n}: {title}")
        print(f"{'='*60}")


def _print_finding(label: str, value: str, quiet: bool) -> None:
    if not quiet:
        print(f"  {label:<30} {value}")


def run(
    cluster_type: str = "classic",
    kubeconfig: Optional[str] = None,
    namespace: Optional[str] = None,
    workload: Optional[str] = None,
    output: str = "both",
    out_dir: str = "reports/advisor",
    run_id: str = "",
    results_dir: str = "results",
    quiet: bool = False,
) -> dict:
    """
    Run all three phases and write outputs. Returns a summary dict.
    """
    kc = _resolve_kubeconfig(cluster_type, kubeconfig)
    if not quiet:
        print(f"\nAutoscaling Advisor")
        print(f"  cluster_type : {cluster_type}")
        print(f"  kubeconfig   : {kc or '(env)'}")
        print(f"  scope        : {namespace or 'cluster-wide'}{' / ' + workload if workload else ''}")
        print(f"  output       : {output} → {out_dir}")

    # Optional: load benchmark latency data
    bench_lat = load_benchmark_latencies(results_dir)
    if bench_lat and not quiet:
        print(f"  benchmark run: {bench_lat.run_id} ({bench_lat.source_file})")

    # -----------------------------------------------------------------------
    # Phase 1 — Topology Discovery
    # -----------------------------------------------------------------------
    _print_phase(1, "Topology Discovery", quiet)
    t0 = time.monotonic()
    topology = phase1_discover(
        kubeconfig=kc,
        cluster_type=cluster_type,
        namespace_filter=namespace,
    )
    t1 = time.monotonic()

    if not quiet:
        _print_finding("Autoscaler", topology.autoscaler_type, quiet)
        _print_finding("Nodes", str(topology.node_count), quiet)
        _print_finding("HPAs", str(len(topology.hpas)), quiet)
        _print_finding("VPAs", str(len(topology.vpas)), quiet)
        _print_finding("KEDA objects", str(len(topology.keda_objects)), quiet)
        _print_finding("PDBs", str(len(topology.pdbs)), quiet)
        _print_finding("Structural findings", str(len(topology.findings)), quiet)
        for f in topology.findings:
            print(f"    [{f.severity.upper():8s}] {f.finding_id}: {f.detail}")
        print(f"  completed in {t1-t0:.1f}s")

    # -----------------------------------------------------------------------
    # Phase 2 — Workload Observation
    # -----------------------------------------------------------------------
    _print_phase(2, "Workload Observation", quiet)
    t0 = time.monotonic()
    obs = phase2_observe(
        topology=topology,
        kubeconfig=kc,
        namespace_filter=namespace,
        benchmark_latencies=bench_lat,
    )
    t1 = time.monotonic()

    if not quiet:
        _print_finding("Prometheus available", str(obs.prometheus_available), quiet)
        _print_finding("Provision latency", f"{obs.provision_latency_s:.0f}s ({obs.provision_latency_source})", quiet)
        _print_finding("Workloads observed", str(len(obs.workloads)), quiet)
        for wo in obs.workloads:
            conf_note = f" [{wo.confidence}]"
            pattern = f" pattern={wo.pattern.classification}" if wo.pattern else ""
            print(f"    {wo.namespace}/{wo.name}{conf_note}{pattern}")
        print(f"  completed in {t1-t0:.1f}s")

    # -----------------------------------------------------------------------
    # Phase 3 — Reasoning
    # -----------------------------------------------------------------------
    _print_phase(3, "Reasoning & Recommendations", quiet)
    t0 = time.monotonic()
    reasoning = phase3_reason(topology=topology, obs=obs)
    t1 = time.monotonic()

    if not quiet:
        s = reasoning.summary
        print(f"  {s.get('total_recommendations',0)} total recommendations:")
        print(f"    critical : {s.get('critical',0)}")
        print(f"    warning  : {s.get('warning',0)}")
        print(f"    info     : {s.get('info',0)}")
        for r in reasoning.recommendations:
            icon = "🔴" if r.severity == "critical" else "🟠" if r.severity == "warning" else "🔵"
            print(f"    {icon} [{r.rec_id}] {r.workload}: {r.finding_type}")
        for r in reasoning.cluster_recs:
            print(f"    🔴 [{r.rec_id}] {r.workload}: {r.finding_type}")
        print(f"  completed in {t1-t0:.1f}s")

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------
    outputs = {}
    os.makedirs(out_dir, exist_ok=True)

    if output in ("html", "both"):
        html_path = canvas_out.render(topology, obs, reasoning, run_id=run_id, out_dir=out_dir)
        outputs["html"] = html_path
        if not quiet:
            print(f"\n  HTML report: {html_path}")

    if output in ("json", "both"):
        json_path = json_out.write(topology, obs, reasoning, out_dir=out_dir, run_id=run_id)
        outputs["json"] = json_path
        if not quiet:
            print(f"  JSON report: {json_path}")

    return {
        "summary": reasoning.summary,
        "outputs": outputs,
        "topology": topology,
        "observations": obs,
        "reasoning": reasoning,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autoscaling Advisor — analyze a ROSA cluster and produce recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cluster-type", default="classic",
                        choices=["classic", "hcp", "hcp-autonode"],
                        help="Cluster type (default: classic)")
    parser.add_argument("--kubeconfig", default=None,
                        help="Path to kubeconfig (default: KUBECONFIG env or auto-detect)")
    parser.add_argument("--namespace", default=None,
                        help="Scope analysis to a namespace (default: cluster-wide)")
    parser.add_argument("--workload", default=None,
                        help="Scope to a specific deployment name")
    parser.add_argument("--output", default="both",
                        choices=["json", "html", "both"],
                        help="Output format (default: both)")
    parser.add_argument("--out-dir", default="reports/advisor",
                        help="Output directory (default: reports/advisor)")
    parser.add_argument("--run-id", default="",
                        help="Benchmark run ID for events.jsonl lookup")
    parser.add_argument("--results-dir", default="results",
                        help="Directory containing benchmark results/ (default: results)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress progress output")

    args = parser.parse_args()

    result = run(
        cluster_type=args.cluster_type,
        kubeconfig=args.kubeconfig,
        namespace=args.namespace,
        workload=args.workload,
        output=args.output,
        out_dir=args.out_dir,
        run_id=args.run_id,
        results_dir=args.results_dir,
        quiet=args.quiet,
    )

    s = result["summary"]
    if s.get("critical", 0) > 0:
        print(f"\n⚠  {s['critical']} critical finding(s) require attention.")
        sys.exit(1)
    else:
        print(f"\n✓  Advisor complete. {s.get('total_recommendations',0)} recommendations written to {args.out_dir}")
        sys.exit(0)


if __name__ == "__main__":
    main()
