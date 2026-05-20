/**
 * k6 scenario: ramp
 *
 * Linear ramp from baseline to PEAK_RPS over 10 minutes, hold for 5 minutes,
 * then ramp back down. Designed to find at what utilization HPA fires relative
 * to when latency actually starts degrading.
 *
 * Validates:
 *   - HPA threshold calibration (does HPA fire before or after p99 breaches SLO?)
 *   - R1 finding: if latency degrades before HPA fires, threshold is too high
 *   - Scale-down stabilization window (does HPA thrash on the way down?)
 *
 * Environment variables:
 *   TARGET_HOST   (default: see thresholds.js)
 *   BASELINE_RPS  (default: 30)
 *   PEAK_RPS      (default: 150, i.e., 5× baseline)
 */

import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";
import { TARGET_HOST, SLO_THRESHOLDS, pickEndpoint } from "./lib/thresholds.js";

const errors = new Rate("errors");

const BASELINE_RPS = parseInt(__ENV.BASELINE_RPS || "30");
const PEAK_RPS     = parseInt(__ENV.PEAK_RPS     || "150");

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-arrival-rate",
      startRate: BASELINE_RPS,
      timeUnit: "1s",
      preAllocatedVUs: PEAK_RPS * 3,
      maxVUs: PEAK_RPS * 6,
      stages: [
        { target: PEAK_RPS,     duration: "10m" }, // ramp up
        { target: PEAK_RPS,     duration: "5m"  }, // hold at peak
        { target: BASELINE_RPS, duration: "5m"  }, // ramp down
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
    tags: { endpoint: path },
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
    "/results/k6-ramp-summary.json": JSON.stringify(data, null, 2),
  };
}
