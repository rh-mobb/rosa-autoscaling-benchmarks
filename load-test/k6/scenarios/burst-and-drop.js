/**
 * k6 scenario: burst-and-drop
 *
 * Brief 5× burst for 2 minutes then an immediate drop back to baseline.
 * The post-burst period runs for 8 minutes to observe whether HPA over-scales
 * and how quickly it scales back down.
 *
 * Validates:
 *   - HPA stabilizationWindowSeconds for scale-down (thrashing prevention)
 *   - Over-scaling: does HPA provision far more replicas than needed?
 *   - Whether scale-down delay creates wasted node cost
 *   - R1 finding: a poorly tuned stabilizationWindowSeconds causes either
 *     thrashing (too low) or expensive over-scale (too high)
 *
 * Environment variables:
 *   TARGET_HOST    (default: see thresholds.js)
 *   BASELINE_RPS   (default: 30)
 *   BURST_RPS      (default: 150, i.e., 5× baseline)
 */

import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";
import { TARGET_HOST, SLO_THRESHOLDS, pickEndpoint } from "./lib/thresholds.js";

const errors = new Rate("errors");

const BASELINE_RPS = parseInt(__ENV.BASELINE_RPS || "30");
const BURST_RPS    = parseInt(__ENV.BURST_RPS    || "150");

export const options = {
  scenarios: {
    // Warm-up: establish baseline before the burst
    warmup: {
      executor: "constant-arrival-rate",
      rate: BASELINE_RPS,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: BASELINE_RPS * 3,
      maxVUs: BASELINE_RPS * 6,
    },
    // The burst: 5× for exactly 2 minutes
    burst: {
      executor: "constant-arrival-rate",
      rate: BURST_RPS,
      timeUnit: "1s",
      startTime: "30s",
      duration: "2m",
      preAllocatedVUs: BURST_RPS * 2,
      maxVUs: BURST_RPS * 5,
    },
    // Return to baseline and observe HPA scale-down behavior
    post_burst: {
      executor: "constant-arrival-rate",
      rate: BASELINE_RPS,
      timeUnit: "1s",
      startTime: "2m30s",
      duration: "8m",
      preAllocatedVUs: BASELINE_RPS * 3,
      maxVUs: BASELINE_RPS * 8,
    },
  },
  thresholds: SLO_THRESHOLDS,
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"],
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
    "/results/k6-burst-and-drop-summary.json": JSON.stringify(data, null, 2),
  };
}
