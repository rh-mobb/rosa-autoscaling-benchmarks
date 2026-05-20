/**
 * Shared SLO thresholds for all k6 load scenarios.
 *
 * These are deliberately NOT set to abort the test on breach — we want to
 * measure the full degradation window through a spike, not stop early.
 * k6 records threshold breaches in the summary JSON for post-run analysis.
 *
 * Adjust TARGET_HOST via the K6_TARGET_HOST environment variable or the
 * SCENARIO_PARAMS ConfigMap in the Job manifest.
 */

export const TARGET_HOST =
  __ENV.TARGET_HOST || "frontend-proxy.otel-demo.svc:8080";

/** SLO thresholds — recorded but do not abort the test */
export const SLO_THRESHOLDS = {
  // p99 latency under 500ms at steady state
  "http_req_duration{p:99}": ["p(99)<500"],
  // error rate under 1%
  "errors": ["rate<0.01"],
  // p95 latency under 300ms
  "http_req_duration{p:95}": ["p(95)<300"],
};

/**
 * Standard endpoints exercised by all scenarios.
 * Weights approximate realistic shopping behavior.
 *
 * All paths verified against the OTel demo v2.2.0 frontend-proxy (Envoy)
 * routing table. The frontend is a Next.js app; /api/* routes go to its
 * internal API handlers which call downstream microservices.
 */
export const ENDPOINTS = [
  { path: "/",                  weight: 40 }, // homepage (product listing)
  { path: "/api/products",      weight: 30 }, // product catalog API
  { path: "/api/cart",          weight: 20 }, // cart read (no auth needed)
  { path: "/api/recommendations", weight: 10 }, // recommendation widget
];

/**
 * Pick a weighted random endpoint.
 * @returns {string} path
 */
export function pickEndpoint() {
  const total = ENDPOINTS.reduce((s, e) => s + e.weight, 0);
  let r = Math.random() * total;
  for (const e of ENDPOINTS) {
    r -= e.weight;
    if (r <= 0) return e.path;
  }
  return ENDPOINTS[0].path;
}
