#!/usr/bin/env python3
"""Regenerate reports/index.html from HTML reports under reports/.

Optionally enriches timings from results/<run-id>/events.jsonl when present
(hcp.total / classic.total are preferred over parsed HTML when available).

Agents should run this after writing any benchmark HTML under reports/:

    python3 scripts/update-reports-index.py

or: make reports-index
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import escape as html_escape
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
RESULTS_DIR = REPO_ROOT / "results"

INDEX_FILE = REPORTS_DIR / "index.html"
INDEX_DATA_FILE = REPORTS_DIR / "index-data.json"


@dataclass
class ReportRow:
    """One row for the index table and charts."""

    file: str
    report_kind: str
    run_id: str | None
    title: str | None
    cluster_name: str | None
    topology: str | None
    report_generated_iso: str | None
    total_install_seconds: float | None
    total_source: str  # "events.jsonl" | "html" | "none"

    def chart_value_minutes(self) -> float | None:
        if self.total_install_seconds is None:
            return None
        return round(self.total_install_seconds / 60.0, 2)

    def sort_timestamp_ms(self) -> int:
        if self.report_generated_iso:
            try:
                # tolerate Z suffix
                s = self.report_generated_iso.replace("Z", "+00:00")
                if s.endswith("+00:00") or re.search(r"[+-]\d{2}:\d{2}$", s):
                    return int(datetime.fromisoformat(s).timestamp() * 1000)
            except ValueError:
                pass
        m = re.match(r"^(\d{8}T\d{6})", self.file)
        if m:
            try:
                dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
        return 0


def parse_duration_human(text: str) -> float | None:
    """Parse strings like '56m 2s', '~23m 7s', optional hours. Returns seconds."""
    raw = text.strip().removeprefix("~").strip()
    if not raw or raw.upper() == "N/A":
        return None
    h = m = s = 0
    mo = re.search(r"(\d+)\s*h", raw, re.I)
    if mo:
        h = int(mo.group(1))
    mo = re.search(r"(\d+)\s*m", raw, re.I)
    if mo:
        m = int(mo.group(1))
    mo = re.search(r"(\d+)\s*s", raw, re.I)
    if mo:
        s = int(mo.group(1))
    if h == 0 and m == 0 and s == 0:
        return None
    return float(h * 3600 + m * 60 + s)


def _parse_html_report(path: Path) -> dict[str, str | float | None]:
    """Extract fields from benchmark report HTML (test 01 template shape).

    Uses regex — avoids brittle XML parsing of hand-authored HTML.
    """
    raw = path.read_text(encoding="utf-8")
    out: dict[str, str | float | None] = {}

    m = re.search(r"<h1[^>]*>([^<]+)</h1>", raw, re.I)
    if m:
        out["title"] = unescape(m.group(1).strip())

    m = re.search(
        r"<dt>\s*Run ID\s*</dt>\s*<dd[^>]*>\s*<code>([^<]+)</code>",
        raw,
        re.I | re.S,
    )
    if m:
        out["run_id"] = unescape(m.group(1).strip())

    m = re.search(
        r"<dt>\s*Cluster name\s*</dt>\s*<dd[^>]*>\s*<code>([^<]+)</code>",
        raw,
        re.I | re.S,
    )
    if m:
        out["cluster_name"] = unescape(m.group(1).strip())

    m = re.search(
        r"<dt>\s*Report generated\s*</dt>\s*<dd[^>]*>\s*<code>([^<]+)</code>",
        raw,
        re.I | re.S,
    )
    if m:
        code = unescape(m.group(1).strip())
        mo_iso = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)", code)
        out["report_generated_iso"] = mo_iso.group(1) if mo_iso else code

    m = re.search(
        r'<div class="label">\s*([^<]*Total[^<]*wall[^<]*)\s*</div>\s*'
        r'<div class="value">\s*([^<]+?)\s*</div>',
        raw,
        re.I | re.S,
    )
    if m:
        out["html_total_seconds"] = parse_duration_human(unescape(m.group(2).strip()))
    else:
        out["html_total_seconds"] = None

    return out


_PER_TEST_PATTERN = re.compile(
    r"^(?P<run_id>\d{8}T\d{6}-(?:classic|hcp))-"
    r"(?P<num>\d{2})-(?P<topo>classic|hcp)-(?P<slug>[a-z0-9-]+)\.html$"
)

_TEST_NUM_LABELS: dict[str, str] = {
    "02": "02 · Machine pool",
    "03": "03 · CAS scale-up",
    "04": "04 · CAS scale-down",
    "05": "05 · Unschedulable",
    "06": "06 · HPA",
    "07": "07 · VPA advise",
    "08": "08 · HPA → CAS",
    "09": "09 · Overprovisioning",
}


def classify_report(filename: str) -> tuple[str, str | None]:
    """Return (report_kind, topology hint for install reports)."""
    if re.search(r"-01-classic-cluster-install\.html$", filename):
        return "01_cluster_install", "classic"
    if re.search(r"-01-hcp-cluster-install\.html$", filename):
        return "01_cluster_install", "hcp"
    if re.search(r"-suite-01-through-09\.html$", filename):
        return "suite_01_09", None
    m = _PER_TEST_PATTERN.match(filename)
    if m:
        return f"test_{m.group('num')}", m.group("topo")
    return "other", None


def load_jsonl_totals(run_id: str) -> tuple[float | None, float | None]:
    """Return (classic_total_s, hcp_total_s) from events.jsonl if present."""
    path = RESULTS_DIR / run_id / "events.jsonl"
    if not path.exists():
        return None, None
    best: dict[str, float] = {}
    import contextlib

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError, KeyError, TypeError):
                rec = json.loads(line)
                label = rec.get("label")
                elapsed = rec.get("elapsed_ms")
                if isinstance(label, str) and isinstance(elapsed, int | float):
                    best[label] = max(best.get(label, 0), float(elapsed) / 1000.0)
    c = best.get("classic.total")
    h = best.get("hcp.total")
    return (c, h)


def collect_rows() -> list[ReportRow]:
    rows: list[ReportRow] = []
    exclude = {"index.html"}

    for path in sorted(REPORTS_DIR.glob("*.html")):
        if path.name in exclude or path.name.startswith("template-"):
            continue
        kind, topo_hint = classify_report(path.name)
        parsed = _parse_html_report(path)

        rid = parsed.get("run_id")
        run_id: str | None = rid if isinstance(rid, str) else None
        topology = topo_hint
        if not topology and run_id:
            if run_id.endswith("-classic"):
                topology = "classic"
            elif run_id.endswith("-hcp"):
                topology = "hcp"

        total_s: float | None = None
        src = "none"
        c_j, h_j = (None, None)
        if run_id:
            c_j, h_j = load_jsonl_totals(run_id)
            if topology == "classic" and c_j is not None:
                total_s, src = c_j, "events.jsonl"
            elif topology == "hcp" and h_j is not None:
                total_s, src = h_j, "events.jsonl"
            elif c_j is not None and topology is None:
                total_s, src = c_j, "events.jsonl"
            elif h_j is not None and topology is None:
                total_s, src = h_j, "events.jsonl"

        html_total = parsed.get("html_total_seconds")
        if (
            total_s is None
            and isinstance(html_total, int | float)
            and html_total is not None
        ):
            total_s, src = float(html_total), "html"

        title_raw = parsed.get("title")
        title: str | None = title_raw if isinstance(title_raw, str) else None
        cn_raw = parsed.get("cluster_name")
        cluster_name: str | None = cn_raw if isinstance(cn_raw, str) else None
        rg_raw = parsed.get("report_generated_iso")
        report_generated_iso: str | None = rg_raw if isinstance(rg_raw, str) else None

        rows.append(
            ReportRow(
                file=path.name,
                report_kind=kind,
                run_id=run_id,
                title=title,
                cluster_name=cluster_name,
                topology=topology,
                report_generated_iso=report_generated_iso,
                total_install_seconds=total_s,
                total_source=src,
            )
        )
    rows.sort(key=lambda r: r.sort_timestamp_ms(), reverse=True)
    return rows


def render_html(rows: list[ReportRow], generated_iso: str) -> str:
    chart_points: dict[str, list[tuple[int, str, float]]] = {"classic": [], "hcp": []}
    for r in rows:
        if r.report_kind != "01_cluster_install":
            continue
        m = r.chart_value_minutes()
        if m is None or r.topology not in chart_points:
            continue
        label = r.report_generated_iso or r.run_id or r.file
        chart_points[r.topology].append((r.sort_timestamp_ms(), str(label), m))

    chart_series: dict[str, dict[str, list[str | float]]] = {}
    for topo, pts in chart_points.items():
        pts_sorted = sorted(pts, key=lambda t: t[0])
        chart_series[topo] = {
            "labels": [p[1] for p in pts_sorted],
            "data": [p[2] for p in pts_sorted],
        }

    installs = [r for r in rows if r.report_kind == "01_cluster_install"]
    latest_classic = next((r for r in installs if r.topology == "classic"), None)
    latest_hcp = next((r for r in installs if r.topology == "hcp"), None)
    suites = [r for r in rows if r.report_kind == "suite_01_09"]

    def esc(s: str | None) -> str:
        return html_escape(s or "—", quote=True)

    def fmt_total(r: ReportRow | None) -> str:
        if r is None:
            return "—"
        if r.total_install_seconds is None:
            return "—"
        sec = int(r.total_install_seconds)
        return f"{sec // 3600}h {(sec % 3600) // 60}m {sec % 60}s ({r.total_source})"

    rows_json = json.dumps([asdict(r) for r in rows], indent=2)
    chart_json = json.dumps(chart_series, indent=2)

    latest_rows_html = ""
    for label, rec in (
        ("Latest Classic cluster install (test 01)", latest_classic),
        ("Latest HCP cluster install (test 01)", latest_hcp),
    ):
        if rec:
            latest_rows_html += f"""
        <div class="card">
          <div class="card-label">{esc(label)}</div>
          <div class="card-value">{esc(fmt_total(rec))}</div>
          <div class="card-meta">Run <code>{esc(rec.run_id)}</code> · {esc(rec.report_generated_iso)}</div>
          <a class="card-link" href="{esc(rec.file)}">Open report</a>
        </div>"""
        else:
            latest_rows_html += f"""
        <div class="card muted">
          <div class="card-label">{esc(label)}</div>
          <div class="card-value">No report yet</div>
        </div>"""

    # Build a map from run_id → install report filename for cross-linking
    install_report_map: dict[str, str] = {}
    for r in rows:
        if r.report_kind == "01_cluster_install" and r.run_id:
            install_report_map[r.run_id] = r.file

    table_body = ""
    for r in rows:
        if r.report_kind == "01_cluster_install":
            kind_display = "01 · Cluster install"
        elif r.report_kind == "suite_01_09":
            kind_display = "Suite · 01-09"
        elif r.report_kind.startswith("test_"):
            num = r.report_kind.split("_")[1]
            kind_display = _TEST_NUM_LABELS.get(num, f"{num} · test")
        else:
            kind_display = "Other"

        total_cell = fmt_total(r) if r.report_kind == "01_cluster_install" else "—"

        # For per-test reports, add a cross-link to the cluster install report
        install_link_cell = ""
        if r.report_kind.startswith("test_") and r.run_id and r.run_id in install_report_map:
            install_file = install_report_map[r.run_id]
            install_link_cell = f'<a href="{esc(install_file)}" title="Cluster install report">↗ install</a>'

        table_body += f"""
        <tr>
          <td><a href="{esc(r.file)}">{esc(r.file)}</a>{' ' + install_link_cell if install_link_cell else ''}</td>
          <td>{esc(kind_display)}</td>
          <td>{esc(r.topology)}</td>
          <td><code>{esc(r.run_id)}</code></td>
          <td>{esc(r.report_generated_iso)}</td>
          <td>{esc(total_cell)}</td>
        </tr>"""

    suite_note = ""
    if suites:
        suite_note = f"<p><strong>Latest suite HTML:</strong> <a href=\"{esc(suites[0].file)}\">{esc(suites[0].file)}</a></p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Benchmark reports — index</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js" crossorigin="anonymous"></script>
  <style>
    :root {{
      --bg: #0f1419;
      --surface: #1a2332;
      --border: #2d3a4d;
      --text: #e6edf3;
      --muted: #8b9cb3;
      --accent: #58a6ff;
      --ok: #3fb950;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      font-size: 15px;
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
    h1 {{ font-size: 1.35rem; margin: 0 0 0.5rem; }}
    .subtitle {{ color: var(--muted); margin: 0 0 1.5rem; }}
    .grid-latest {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.1rem;
    }}
    .card.muted {{ opacity: 0.75; }}
    .card-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
    .card-value {{ font-size: 1.1rem; font-weight: 600; margin: 0.35rem 0; font-variant-numeric: tabular-nums; }}
    .card-meta {{ font-size: 0.82rem; color: var(--muted); margin-bottom: 0.5rem; }}
    .card-link {{ color: var(--accent); font-size: 0.9rem; }}
    .chart-wrap {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.25rem 1.5rem;
      margin: 2rem 0;
      min-height: 320px;
    }}
    .chart-wrap h2 {{ font-size: 1.05rem; color: var(--accent); margin: 0 0 1rem; }}
    canvas {{ max-height: 340px; }}
    table.reports {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      margin-top: 0.5rem;
    }}
    table.reports th, table.reports td {{
      text-align: left;
      padding: 0.5rem 0.6rem;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    table.reports th {{ color: var(--muted); font-weight: 500; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    table.reports a {{ color: var(--accent); }}
    code {{ font-size: 0.85em; }}
    footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: 0.82rem; color: var(--muted); }}
    pre.data {{ display: none; }}
  </style>
</head>
<body>
  <main>
    <h1>Benchmark HTML reports</h1>
    <p class="subtitle">Generated <code>{esc(generated_iso)}</code> · Lower install time (minutes) on the chart usually means faster runs — compare under similar conditions only.</p>

    <div class="grid-latest">
      {latest_rows_html}
    </div>
    {suite_note}

    <div class="chart-wrap">
      <h2>Cluster install total (minutes) over time</h2>
      <p class="subtitle" style="margin-top:-0.25rem">Test 01 — uses <code>*.total</code> from <code>events.jsonl</code> when available, otherwise the &ldquo;Total (wall clock)&rdquo; stat from each HTML report.</p>
      <canvas id="trendChart" aria-label="Install duration trend"></canvas>
    </div>

    <h2 style="font-size:1.05rem;color:var(--accent)">All reports (newest first)</h2>
    <table class="reports">
      <thead>
        <tr>
          <th>File</th>
          <th>Kind</th>
          <th>Topology</th>
          <th>Run ID</th>
          <th>Report time (UTC)</th>
          <th>Install total</th>
        </tr>
      </thead>
      <tbody>
        {table_body}
      </tbody>
    </table>

    <footer>
      Regenerate after adding reports: <code>python3 scripts/update-reports-index.py</code> or <code>make reports-index</code>.
    </footer>
  </main>
  <pre class="data" id="chart-data">{chart_json}</pre>
  <pre class="data" id="rows-data">{rows_json}</pre>
  <script>
    (function () {{
      const el = document.getElementById("chart-data");
      const chartSpec = JSON.parse(el.textContent);
      const classic = chartSpec.classic || {{ labels: [], data: [] }};
      const hcp = chartSpec.hcp || {{ labels: [], data: [] }};
      const allLabels = [...new Set([...classic.labels, ...hcp.labels])];
      allLabels.sort();

      const ctx = document.getElementById("trendChart");
      const hasData =
        (classic.labels && classic.labels.length > 0) ||
        (hcp.labels && hcp.labels.length > 0);
      if (!hasData) {{
        ctx.replaceWith(Object.assign(document.createElement("p"), {{
          className: "subtitle",
          textContent: "No test 01 install reports with parseable totals yet — add HTML reports and re-run the index script.",
        }}));
        return;
      }}

      function alignSeries(series) {{
        const map = Object.fromEntries(series.labels.map((lb, i) => [lb, series.data[i]]));
        return allLabels.map((lb) => (map[lb] !== undefined ? map[lb] : null));
      }}

      new Chart(ctx, {{
        type: "line",
        data: {{
          labels: allLabels,
          datasets: [
            {{
              label: "Classic · install total (min)",
              data: alignSeries(classic),
              borderColor: "#58a6ff",
              backgroundColor: "rgba(88, 166, 255, 0.15)",
              tension: 0.2,
              spanGaps: true,
            }},
            {{
              label: "HCP · install total (min)",
              data: alignSeries(hcp),
              borderColor: "#3fb950",
              backgroundColor: "rgba(63, 185, 80, 0.12)",
              tension: 0.2,
              spanGaps: true,
            }},
          ],
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          scales: {{
            x: {{
              title: {{ display: true, text: "Report timestamp / id" }},
              ticks: {{ maxRotation: 45, minRotation: 0 }},
            }},
            y: {{
              title: {{ display: true, text: "Minutes" }},
              beginAtZero: true,
            }},
          }},
          plugins: {{
            legend: {{ position: "bottom" }},
            tooltip: {{
              callbacks: {{
                label: (c) => c.dataset.label + ": " + (c.parsed.y != null ? c.parsed.y + " min" : "—"),
              }},
            }},
          }},
        }},
      }});
    }})();
  </script>
</body>
</html>
"""


def write_index_data(rows: list[ReportRow], generated_iso: str) -> None:
    payload = {
        "generated_at": generated_iso,
        "reports": [asdict(r) for r in rows],
    }
    INDEX_DATA_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print HTML to stdout instead of writing reports/index.html",
    )
    args = parser.parse_args()

    rows = collect_rows()
    generated = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = render_html(rows, generated)
    if args.stdout:
        print(out)
        return 0
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(out, encoding="utf-8")
    write_index_data(rows, generated)
    print(f"Wrote {INDEX_FILE} ({len(rows)} reports)", file=__import__("sys").stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
