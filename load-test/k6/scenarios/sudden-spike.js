/**
 * k6 scenario: sudden-spike
 *
 * Simulates an unplanned traffic event (influencer post, flash sale announcement)
 * that immediately drives 10× the baseline request rate.
 *
 * Phase 1 (0–60s):   baseline traffic at BASELINE_RPS
 * Phase 2 (60–360s): spike at SPIKE_RPS (default 10× baseline)
 * Phase 3 (360–480s): recovery back to baseline
 *
 * Validates:
 *   - How quickly HPA fires and new pods become Ready
 *   - Whether balloon pods collapse the error window (Phase 2 advisor rec)
 *   - Degradation window: seconds from spike start until error_rate < 1%
 *
 * Environment variables (set via k6 Job ConfigMap):
 *   TARGET_HOST    — frontend-proxy service address (default: see thresholds.js)
 *   BASELINE_RPS   — requests/s before spike (default: 30)
 *   SPIKE_RPS      — requests/s during spike (default: 300)
 *   SPIKE_AT_S     — seconds before spike fires (default: 60)
 *   TOTAL_S        — total scenario duration in seconds (default: 480)
 */

import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";
import { TARGET_HOST, SLO_THRESHOLDS, pickEndpoint } from "./lib/thresholds.js";

const errors = new Rate("errors");

const BASELINE_RPS = parseInt(__ENV.BASELINE_RPS || "30");
const SPIKE_RPS    = parseInt(__ENV.SPIKE_RPS    || "300");
const SPIKE_AT_S   = parseInt(__ENV.SPIKE_AT_S   || "60");
const TOTAL_S      = parseInt(__ENV.TOTAL_S      || "480");
// Recovery window: default 120s, but never more than 40% of remaining time after spike
const RECOVERY_S   = Math.min(120, Math.floor((TOTAL_S - SPIKE_AT_S) * 0.4));

export const options = {
  scenarios: {
    baseline: {
      executor: "constant-arrival-rate",
      rate: BASELINE_RPS,
      timeUnit: "1s",
      duration: `${SPIKE_AT_S}s`,
      preAllocatedVUs: BASELINE_RPS * 3,
      maxVUs: BASELINE_RPS * 10,
    },
    spike: {
      executor: "constant-arrival-rate",
      rate: SPIKE_RPS,
      timeUnit: "1s",
      startTime: `${SPIKE_AT_S}s`,
      duration: `${TOTAL_S - SPIKE_AT_S - RECOVERY_S}s`,
      preAllocatedVUs: SPIKE_RPS * 2,
      maxVUs: SPIKE_RPS * 5,
    },
    recovery: {
      executor: "ramping-arrival-rate",
      startTime: `${TOTAL_S - RECOVERY_S}s`,
      startRate: SPIKE_RPS,
      timeUnit: "1s",
      preAllocatedVUs: BASELINE_RPS * 5,
      maxVUs: SPIKE_RPS * 3,
      stages: [
        { target: BASELINE_RPS, duration: `${RECOVERY_S}s` },
      ],
    },
  },
  thresholds: SLO_THRESHOLDS,
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "p(99.9)", "max"],
};

const BASE_URL = `http://${TARGET_HOST}`;

export default function () {
  const path = pickEndpoint();
  const res = http.get(`${BASE_URL}${path}`, {
    headers: { "Accept": "application/json" },
    tags: {
      scenario: __ENV.K6_SCENARIO_NAME || "spike",
      endpoint: path,
    },
    timeout: "10s",
  });

  const ok = check(res, {
    "status 2xx": (r) => r.status >= 200 && r.status < 300,
    "no 5xx":     (r) => r.status < 500,
  });
  errors.add(!ok);
}

export function handleSummary(data) {
  return {
    "/results/k6-sudden-spike-summary.json": JSON.stringify(data, null, 2),
  };
}
