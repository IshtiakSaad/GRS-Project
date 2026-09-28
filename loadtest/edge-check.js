// The edge limit, through Nginx: one address hammering the login route is cut to about
// 10 requests a second (plus a burst of 40), with the API's JSON error body, not an HTML page.
//   BASE_URL  the public site, e.g. https://demo.example.org

import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const BASE = __ENV.BASE_URL || "https://nginx";
const limited = new Counter("edge_limited");
const passed = new Counter("edge_passed");

export const options = {
  insecureSkipTLSVerify: !!__ENV.INSECURE,
  scenarios: {
    hammer: {
      executor: "constant-arrival-rate",
      rate: 60, // six times the per-address login allowance
      timeUnit: "1s",
      duration: "10s",
      preAllocatedVUs: 30,
    },
  },
  thresholds: {
    edge_limited: ["count>300"], // most of the 600 are refused at the edge
    edge_passed: ["count<200"], // about 10/s + the burst get through
    checks: ["rate>0.99"],
  },
};

export default function () {
  const headers = { "Content-Type": "application/json" };
  if (__ENV.HOST) headers.Host = __ENV.HOST;
  // A different unknown number each time, so the app's per-phone limit never applies and
  // only the edge is measured; what gets through is refused by the app (401).
  const phone = `+88010${String(Math.floor(Math.random() * 1e8)).padStart(8, "0")}`;
  const r = http.post(
    `${BASE}/api/v1/auth/login`,
    JSON.stringify({ phone, password: "wrong-password" }),
    { headers },
  );
  if (r.status === 429) limited.add(1);
  else passed.add(1);
  check(r, {
    "limited or refused": (x) => x.status === 429 || x.status === 401,
    "429 carries the API error body": (x) =>
      x.status !== 429 || (x.json("error.code") === "RATE_LIMITED" && !!x.headers["Retry-After"]),
  });
}
