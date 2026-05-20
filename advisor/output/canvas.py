"""
HTML canvas output — renders the advisor report as a self-contained HTML page
with the same section structure as the Cursor Canvas:

1. Infrastructure Summary (stat row)
2. Structural Findings (severity-sorted table)
3. Per-workload Finding Cards
4. Cluster-wide Recommendations
5. Confidence Notes
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from ..lib.sizing import format_cpu, format_memory


# ---------------------------------------------------------------------------
# Severity → CSS colour mapping
# ---------------------------------------------------------------------------
SEVERITY_COLOR = {
    "critical": "#c0392b",
    "warning":  "#e67e22",
    "info":     "#2980b9",
}

SEVERITY_BG = {
    "critical": "#fdf2f2",
    "warning":  "#fef9f0",
    "info":     "#f0f7fe",
}

CONFIDENCE_COLOR = {
    "high":   "#27ae60",
    "medium": "#f39c12",
    "low":    "#95a5a6",
}


def _badge(text: str, color: str, bg: str = "#eee") -> str:
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
        f'font-size:11px;font-weight:700;color:{color};background:{bg};">'
        f"{text}</span>"
    )


def _sev_badge(severity: str) -> str:
    c = SEVERITY_COLOR.get(severity, "#666")
    bg = SEVERITY_BG.get(severity, "#eee")
    return _badge(severity.upper(), c, bg)


def _conf_badge(confidence: str) -> str:
    c = CONFIDENCE_COLOR.get(confidence, "#666")
    return _badge(f"confidence: {confidence}", c, "#f9f9f9")


def _autoscaler_icon(atype: str) -> str:
    icons = {
        "cas": "⚙️ CAS",
        "karpenter": "⚡ Karpenter",
        "none": "⚠️ None",
    }
    return icons.get(atype, atype)


def _stat_card(label: str, value: str, sub: str = "") -> str:
    return f"""
    <div style="background:#fff;border:1px solid #dde;border-radius:8px;
                padding:16px 20px;min-width:120px;text-align:center;">
      <div style="font-size:28px;font-weight:700;color:#1a1a2e;">{value}</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">{label}</div>
      {f'<div style="font-size:11px;color:#999;margin-top:2px;">{sub}</div>' if sub else ''}
    </div>"""


def render(
    topology,
    obs,
    reasoning,
    run_id: str = "",
    out_dir: str = "reports/advisor",
) -> str:
    """Render the full HTML report and write it to out_dir/advisor_report.html."""
    os.makedirs(out_dir, exist_ok=True)
    html = _build_html(topology, obs, reasoning, run_id)
    path = os.path.join(out_dir, "advisor_report.html")
    with open(path, "w") as fp:
        fp.write(html)
    return path


def _build_html(topology, obs, reasoning, run_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = [
        _section_header(topology, obs, reasoning, ts, run_id),
        _section_infra_summary(topology, obs),
        _section_structural_findings(topology),
        _section_workload_cards(reasoning, category="performance"),
        _section_cluster_recs(reasoning),
        _section_workload_cards(reasoning, category="cost"),
        _section_confidence_notes(obs, topology),
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Autoscaling Advisor — {topology.cluster_type}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f4f5f7;
      color: #1a1a2e;
      line-height: 1.5;
    }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px; }}
    h2 {{ font-size: 18px; font-weight: 700; margin: 32px 0 12px; color: #1a1a2e; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }}
    h3 {{ font-size: 15px; font-weight: 600; margin: 16px 0 8px; }}
    .card {{
      background: #fff;
      border: 1px solid #dde;
      border-radius: 10px;
      padding: 18px 22px;
      margin-bottom: 16px;
      border-left: 4px solid #ccc;
    }}
    .card.critical {{ border-left-color: #c0392b; }}
    .card.warning  {{ border-left-color: #e67e22; }}
    .card.info     {{ border-left-color: #2980b9; }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .card-title {{ font-size: 15px; font-weight: 700; font-family: monospace; }}
    .card-badges {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .row {{ display: flex; gap: 8px; margin: 4px 0; flex-wrap: wrap; }}
    .label {{ font-size: 12px; font-weight: 600; color: #666; min-width: 130px; flex-shrink: 0; }}
    .value {{ font-size: 13px; color: #333; }}
    pre.yaml {{
      background: #1e1e2e;
      color: #cdd6f4;
      padding: 14px;
      border-radius: 6px;
      font-size: 12px;
      overflow-x: auto;
      margin-top: 10px;
      white-space: pre-wrap;
      word-break: break-all;
    }}
    .stats-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-top: 8px;
    }}
    th {{ background: #f8f8fc; padding: 8px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #dde; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: top; }}
    tr:hover td {{ background: #fafbff; }}
    .tag {{ display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;background:#e8eaf6;color:#3949ab;margin:1px; }}
  </style>
</head>
<body>
<div class="page">
{''.join(sections)}
</div>
</body>
</html>"""


def _section_header(topology, obs, reasoning, ts: str, run_id: str) -> str:
    s = reasoning.summary
    critical = s.get("critical", 0)
    total = s.get("total_recommendations", 0)
    perf_count = s.get("performance_count", 0)
    cost_count = s.get("cost_count", 0)
    run_info = f" &nbsp;·&nbsp; Run: <code>{run_id}</code>" if run_id else ""
    crit_style = "color:#c0392b;font-weight:700;" if critical > 0 else "color:#27ae60;font-weight:700;"
    return f"""
<div style="background:#1a1a2e;color:#fff;border-radius:12px;padding:28px 32px;margin-bottom:24px;">
  <h1 style="font-size:24px;font-weight:800;margin-bottom:8px;">
    Autoscaling Advisor
  </h1>
  <div style="opacity:.8;font-size:14px;">
    Cluster: <strong>{topology.cluster_type}</strong> &nbsp;·&nbsp;
    Autoscaler: <strong>{topology.autoscaler_type}</strong> &nbsp;·&nbsp;
    Generated: {ts}{run_info}
  </div>
  <div style="margin-top:16px;display:flex;gap:32px;flex-wrap:wrap;">
    <div>
      <div style="font-size:11px;opacity:.6;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">Performance</div>
      <div style="font-size:32px;{crit_style}">{perf_count}</div>
      <div style="font-size:12px;opacity:.75;margin-top:2px;">
        <span style="color:#ff6b6b;">{critical} critical</span> &nbsp;·&nbsp;
        <span style="color:#ffa94d;">{s.get('warning', 0)} warning</span> &nbsp;·&nbsp;
        <span style="color:#74c0fc;">{s.get('info', 0)} info</span>
      </div>
    </div>
    <div style="width:1px;background:rgba(255,255,255,.15);margin:0 4px;"></div>
    <div>
      <div style="font-size:11px;opacity:.6;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">Cost Optimization</div>
      <div style="font-size:32px;font-weight:700;color:#51cf66;">{cost_count}</div>
      <div style="font-size:12px;opacity:.75;margin-top:2px;">opportunities</div>
    </div>
  </div>
</div>"""


def _section_infra_summary(topology, obs) -> str:
    hpa_c = len(topology.hpas)
    vpa_c = len(topology.vpas)
    keda_c = len(topology.keda_objects)
    pdb_c = len(topology.pdbs)

    ready_nodes = sum(1 for n in topology.nodes if n.ready)
    pool_rows = "".join(
        f"<tr><td><code>{p.name}</code></td><td>{p.instance_type}</td>"
        f"<td>{p.ready}/{p.desired}</td></tr>"
        for p in topology.machine_pools
    ) or "<tr><td colspan='3' style='color:#999'>No MachineSets found</td></tr>"

    prom_status = (
        f'<span style="color:#27ae60;">✓ available</span> ({obs.prom_endpoint})'
        if obs.prometheus_available else
        '<span style="color:#e67e22;">⚠ unavailable — recommendations at lower confidence</span>'
    )
    provision_src = obs.provision_latency_source
    provision_s = obs.provision_latency_s

    return f"""
<h2>Infrastructure Summary</h2>
<div class="stats-row">
  {_stat_card('Nodes', str(topology.node_count), f'{ready_nodes} ready')}
  {_stat_card('HPAs', str(hpa_c))}
  {_stat_card('VPAs', str(vpa_c))}
  {_stat_card('KEDA', str(keda_c))}
  {_stat_card('PDBs', str(pdb_c))}
  {_stat_card('Autoscaler', _autoscaler_icon(topology.autoscaler_type))}
  {_stat_card('Prov. latency', f'{provision_s:.0f}s', provision_src)}
</div>
<h3>Machine Pools / NodePools</h3>
<table>
  <tr><th>Name</th><th>Instance type</th><th>Ready/Desired</th></tr>
  {pool_rows}
</table>
<div style="margin-top:12px;font-size:13px;">
  Prometheus: {prom_status}
</div>"""


def _section_structural_findings(topology) -> str:
    if not topology.findings:
        return """
<h2>Structural Findings</h2>
<div style="background:#eafaf1;border:1px solid #a9dfbf;border-radius:8px;padding:14px 18px;color:#1e8449;">
  ✓ No structural issues detected.
</div>"""

    # Sort: critical first
    order = {"critical": 0, "warning": 1, "info": 2}
    sorted_findings = sorted(topology.findings, key=lambda f: order.get(f.severity, 3))

    rows = "".join(
        f"<tr>"
        f"<td>{_sev_badge(f.severity)}</td>"
        f"<td><code>{f.finding_id}</code></td>"
        f"<td><code>{f.namespace}</code></td>"
        f"<td>{f.workload or '—'}</td>"
        f"<td>{f.detail}</td>"
        f"</tr>"
        for f in sorted_findings
    )
    return f"""
<h2>Structural Findings</h2>
<table>
  <tr><th>Severity</th><th>Finding</th><th>Namespace</th><th>Workload</th><th>Detail</th></tr>
  {rows}
</table>"""


SECTION_META = {
    "performance": {
        "heading": "Performance Findings",
        "icon": "⚡",
        "empty_msg": "✓ No performance issues detected.",
        "empty_bg": "#eafaf1",
        "empty_border": "#a9dfbf",
        "empty_color": "#1e8449",
        "subtitle": "Scaling correctness, latency, and reliability — fix these first.",
    },
    "cost": {
        "heading": "Cost Optimization Opportunities",
        "icon": "💰",
        "empty_msg": "No cost recommendations — cost optimization requires confirmed multi-arch images or stateless workload verification.",
        "empty_bg": "#f0f7fe",
        "empty_border": "#90caf9",
        "empty_color": "#1565c0",
        "subtitle": "Reduce compute spend once performance findings are resolved.",
    },
}


def _section_workload_cards(reasoning, category: str = "performance") -> str:
    meta = SECTION_META[category]
    filtered = [r for r in reasoning.recommendations if r.category == category]

    if not filtered:
        return f"""
<h2>{meta['icon']} {meta['heading']}</h2>
<p style="font-size:13px;color:#888;margin-bottom:8px;">{meta['subtitle']}</p>
<div style="background:{meta['empty_bg']};border:1px solid {meta['empty_border']};border-radius:8px;padding:14px 18px;color:{meta['empty_color']};">
  {meta['empty_msg']}
</div>"""

    # Group by workload
    from collections import defaultdict
    by_workload: dict = defaultdict(list)
    for r in filtered:
        by_workload[r.workload].append(r)

    cards_html = ""
    for workload, recs in by_workload.items():
        severity = "critical" if any(r.severity == "critical" for r in recs) else \
                   "warning"  if any(r.severity == "warning"  for r in recs) else "info"
        card_recs = ""
        for r in recs:
            yaml_block = f'<pre class="yaml">{_esc(r.yaml_delta)}</pre>' if r.yaml_delta.strip() else ""
            card_recs += f"""
<div style="border-top:1px solid #eee;padding-top:12px;margin-top:12px;">
  <div class="card-badges" style="margin-bottom:6px;">
    <code style="font-size:13px;font-weight:700;color:#5b2d8e;">{r.rec_id}</code>
    {_sev_badge(r.severity)}
    {_conf_badge(r.confidence)}
    <span class="tag">{r.finding_type}</span>
  </div>
  <div class="row"><span class="label">Finding</span><span class="value">{_esc(r.evidence_detail)}</span></div>
  <div class="row"><span class="label">Evidence</span><span class="value">{_esc(r.metric_value)}</span></div>
  <div class="row"><span class="label">Recommendation</span><span class="value">{_esc(r.recommendation)}</span></div>
  <div class="row"><span class="label">Expected improvement</span><span class="value">{_esc(r.expected_improvement)}</span></div>
  <div class="row"><span class="label">Benchmark ref</span><span class="value">{_esc(r.benchmark_reference)}</span></div>
  {f'<div class="row"><span class="label">Confidence note</span><span class="value" style="color:#888;">{_esc(r.confidence_note)}</span></div>' if r.confidence_note else ''}
  {yaml_block}
</div>"""

        cards_html += f"""
<div class="card {severity}">
  <div class="card-header">
    <div class="card-title">{_esc(workload)}</div>
    <div class="card-badges">
      {_sev_badge(severity)}
      <span style="font-size:12px;color:#888;">{len(recs)} finding{'s' if len(recs) != 1 else ''}</span>
    </div>
  </div>
  {card_recs}
</div>"""

    return f'<h2>{meta["icon"]} {meta["heading"]}</h2><p style="font-size:13px;color:#888;margin-bottom:12px;">{meta["subtitle"]}</p>{cards_html}'


def _section_cluster_recs(reasoning) -> str:
    if not reasoning.cluster_recs:
        return ""

    cards_html = ""
    for r in reasoning.cluster_recs:
        yaml_block = f'<pre class="yaml">{_esc(r.yaml_delta)}</pre>' if r.yaml_delta.strip() else ""
        cards_html += f"""
<div class="card {r.severity}">
  <div class="card-header">
    <div class="card-title">{_esc(r.workload)}</div>
    <div class="card-badges">
      <code style="font-size:13px;font-weight:700;color:#5b2d8e;">{r.rec_id}</code>
      {_sev_badge(r.severity)}
      {_conf_badge(r.confidence)}
    </div>
  </div>
  <div class="row"><span class="label">Finding</span><span class="value">{_esc(r.evidence_detail)}</span></div>
  <div class="row"><span class="label">Recommendation</span><span class="value">{_esc(r.recommendation)}</span></div>
  <div class="row"><span class="label">Expected improvement</span><span class="value">{_esc(r.expected_improvement)}</span></div>
  {yaml_block}
</div>"""

    return f'<h2>⚡ Cluster-wide Performance Findings</h2><p style="font-size:13px;color:#888;margin-bottom:12px;">Infrastructure-level issues affecting the whole cluster.</p>{cards_html}'


def _section_confidence_notes(obs, topology) -> str:
    notes = []
    if not obs.prometheus_available:
        notes.append(
            "Prometheus was not reachable. Traffic pattern analysis was skipped. "
            "All workload recommendations are rated <strong>confidence: low</strong> "
            "unless VPA recommendations were available. "
            "To enable: ensure the cluster's thanos-querier route is accessible or "
            "use <code>oc port-forward</code>."
        )

    vpa_workloads = {v.target_name for v in topology.vpas if v.recommendations}
    if not vpa_workloads:
        notes.append(
            "No VPA recommendations were found. Run VPA in <code>Off</code> (advise-only) mode "
            "for at least 24h to generate right-sizing data: see <code>load-test/manifests/autoscaling/vpa-all-services.yaml</code>."
        )

    if not notes:
        return ""

    notes_html = "".join(f'<li style="margin-bottom:8px;">{n}</li>' for n in notes)
    return f"""
<h2>Confidence Notes</h2>
<div style="background:#fef9f0;border:1px solid #f0c040;border-radius:8px;padding:16px 20px;">
  <ul style="padding-left:20px;font-size:13px;color:#555;">
    {notes_html}
  </ul>
</div>"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
