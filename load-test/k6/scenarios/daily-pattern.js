/**
 * k6 scenario: daily-pattern
 *
 * Compressed 24-hour traffic pattern: quiet overnight, morning ramp, midday
 * peak, afternoon peak, evening wind-down. Runs in ~35 minutes of wall time.
 *
 * Validates:
 *   - Proactive pre-warm effectiveness (R7): does the cluster scale up before
 *     the peak hits, or does each wave start with a degradation window?
 *   - KEDA cron scaler timing: does the email queue drain between waves?
 *   - Whether daily autocorrelation is detectable in the Prometheus metric
 *     history (used by advisor classification question Q5)
 *
 * Environment variables:
 *   TARGET_HOST      (default: see thresholds.js)
 *   BASELINE_RPS     quiet baseline (default: 10)
 *   MORNING_PEAK_RPS morning peak (default: 80)
 *   AFTERNOON_PEAK_RPS afternoon peak (default: 120)
 */

import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";
import { TARGET_HOST, SLO_THRESHOLDS, pickEndpoint } from "./lib/thresholds.js";

const errors = new Rate("errors");

const BASELINE_RPS       = parseInt(__ENV.BASELINE_RPS       || "10");
const MORNING_PEAK_RPS   = parseInt(__ENV.MORNING_PEAK_RPS   || "80");
const AFTERNOON_PEAK_RPS = parseInt(__ENV.AFTERNOON_PEAK_RPS || "120");

export const options = {
  scenarios: {
    daily: {
      executor: "ramping-arrival-rate",
      startRate: BASELINE_RPS,
      timeUnit: "1s",
      preAllocatedVUs: AFTERNOON_PEAK_RPS * 3,
      maxVUs: AFTERNOON_PEAK_RPS * 6,
      stages: [
        // Overnight quiet (compressed: 3 min)
        { target: BASELINE_RPS,       duration: "3m"  },
        // Morning ramp (compressed: 5 min)
        { target: MORNING_PEAK_RPS,   duration: "5m"  },
        // Morning peak (compressed: 4 min)
        { target: MORNING_PEAK_RPS,   duration: "4m"  },
        // Midday dip (compressed: 3 min)
        { target: BASELINE_RPS * 3,   duration: "3m"  },
        // Afternoon ramp (compressed: 4 min)
        { target: AFTERNOON_PEAK_RPS, duration: "4m"  },
        // Afternoon peak (compressed: 5 min)
        { target: AFTERNOON_PEAK_RPS, duration: "5m"  },
        // Evening wind-down (compressed: 6 min)
        { target: BASELINE_RPS * 2,   duration: "3m"  },
        { target: BASELINE_RPS,       duration: "3m"  },
      ],
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
    "/results/k6-daily-pattern-summary.json": JSON.stringify(data, null, 2),
  };
}
