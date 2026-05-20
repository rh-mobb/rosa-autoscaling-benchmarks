/**
 * k6 scenario: sustained-high
 *
 * Holds 3× baseline traffic for 20 minutes, then drops back to baseline.
 * The post-load period continues for 10 minutes so CAS/Karpenter scale-down
 * behavior is visible.
 *
 * Validates:
 *   - CAS scale-down cooldown behavior after load drops (tests ~10 min drain)
 *   - Balloon pod restoration after initial burst consumed headroom
 *   - Whether request errors appear during the ramp-up into sustained load
 *   - R3/R4 balloon pod sizing under sustained (not spike) load
 *
 * Environment variables:
 *   TARGET_HOST     (default: see thresholds.js)
 *   BASELINE_RPS    (default: 30)
 *   SUSTAINED_RPS   (default: 90, i.e., 3× baseline)
 *   HOLD_DURATION   minutes to hold at sustained level (default: 20)
 */

import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";
import { TARGET_HOST, SLO_THRESHOLDS, pickEndpoint } from "./lib/thresholds.js";

const errors = new Rate("errors");

const BASELINE_RPS  = parseInt(__ENV.BASELINE_RPS  || "30");
const SUSTAINED_RPS = parseInt(__ENV.SUSTAINED_RPS || "90");
const HOLD_MIN      = parseInt(__ENV.HOLD_DURATION || "20");

export const options = {
  scenarios: {
    ramp_up: {
      executor: "ramping-arrival-rate",
      startRate: BASELINE_RPS,
      timeUnit: "1s",
      preAllocatedVUs: SUSTAINED_RPS * 3,
      maxVUs: SUSTAINED_RPS * 6,
      stages: [
        { target: SUSTAINED_RPS, duration: "2m" },
      ],
    },
    hold: {
      executor: "constant-arrival-rate",
      rate: SUSTAINED_RPS,
      timeUnit: "1s",
      startTime: "2m",
      duration: `${HOLD_MIN}m`,
      preAllocatedVUs: SUSTAINED_RPS * 2,
      maxVUs: SUSTAINED_RPS * 5,
    },
    ramp_down: {
      executor: "ramping-arrival-rate",
      startRate: SUSTAINED_RPS,
      timeUnit: "1s",
      startTime: `${HOLD_MIN + 2}m`,
      preAllocatedVUs: BASELINE_RPS * 3,
      maxVUs: SUSTAINED_RPS * 3,
      stages: [
        { target: BASELINE_RPS, duration: "2m" },
      ],
    },
    // Continue baseline traffic during scale-down observation window
    post_load: {
      executor: "constant-arrival-rate",
      rate: BASELINE_RPS,
      timeUnit: "1s",
      startTime: `${HOLD_MIN + 4}m`,
      duration: "10m",
      preAllocatedVUs: BASELINE_RPS * 3,
      maxVUs: BASELINE_RPS * 6,
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
    "/results/k6-sustained-high-summary.json": JSON.stringify(data, null, 2),
  };
}
