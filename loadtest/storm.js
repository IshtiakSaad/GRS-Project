// The morning storm: offices open at 9, citizens log in, check their requests and file new
// ones. Three scenarios run together; see loadtest/README.md for how to run and read it.
//
//   AUTH_URL  where password routes go (the api-auth bulkhead)
//   API_URL   everything else
//   USERS, USER_OFFSET  which seed_load_users accounts to use (default the first 300)
//   SCALE     multiplies every arrival rate (default 1: the full storm)
//   HOST      the site's name (GRS_DOMAIN), sent as Host so Django's ALLOWED_HOSTS accepts it
// URLs default to the containers themselves, so the app is measured, not the per-IP edge
// limit that one load generator would hit (edge-check.js covers that separately).

import http from "k6/http";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";
import exec from "k6/execution";

const AUTH = __ENV.AUTH_URL || "http://api-auth:8000";
const API = __ENV.API_URL || "http://api:8000";
const USERS = parseInt(__ENV.USERS || "300");
const PASSWORD = "demo-password-2026";
// Multiplies every arrival rate: SCALE=0.5 is half the storm. Used to find a server's limit.
const SCALE = parseFloat(__ENV.SCALE || "1");
const r = (n) => Math.max(1, Math.round(n * SCALE));
const OFFSET = parseInt(__ENV.USER_OFFSET || "0"); // a fresh slice of accounts per run
const phone = (i) => `+880${1099000000 + OFFSET + (i % USERS)}`;
const BASE_HEADERS = { "Content-Type": "application/json", ...(__ENV.HOST ? { Host: __ENV.HOST } : {}) };
const json = { headers: BASE_HEADERS };

const submitted = new Counter("requests_submitted");
const loginTime = new Trend("login_duration", true);

export const options = {
  scenarios: {
    // A burst of logins: Argon2id on the bulkhead pool.
    login_burst: {
      executor: "ramping-arrival-rate",
      exec: "login",
      startRate: r(5),
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 200,
      stages: [
        { target: r(30), duration: "30s" },
        { target: r(30), duration: "1m" },
        { target: 0, duration: "15s" },
      ],
    },
    // Logged-in citizens reading: list, then one request's detail.
    browse: {
      executor: "constant-arrival-rate",
      exec: "browse",
      rate: r(60),
      timeUnit: "1s",
      duration: "1m45s",
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
    // New requests being filed: draft, then submit with an idempotency key.
    submit: {
      executor: "constant-arrival-rate",
      exec: "submit",
      rate: r(5),
      timeUnit: "1s",
      duration: "1m45s",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: {
    "http_req_failed{scenario:browse}": ["rate<0.01"],
    "http_req_failed{scenario:submit}": ["rate<0.01"],
    "http_req_duration{scenario:browse}": ["p(95)<500"],
    "http_req_duration{scenario:submit}": ["p(95)<1000"],
    "login_duration": ["p(95)<2000"],
    checks: ["rate>0.99"],
  },
};

// One token per virtual user pool slot, made before the storm starts.
export function setup() {
  const tokens = [];
  for (let i = 0; i < Math.min(USERS, 100); i++) {
    const r = http.post(`${AUTH}/api/v1/auth/login`, JSON.stringify({ phone: phone(i), password: PASSWORD }), json);
    if (r.status === 200) tokens.push(r.json("access"));
  }
  const cats = http.get(`${API}/api/v1/categories`, { headers: { ...BASE_HEADERS, Authorization: `Bearer ${tokens[0]}` } });
  const list = cats.json("results") || cats.json();
  if (!tokens.length || !list.length) throw new Error("no load users: run seed_demo and seed_load_users first");
  return { tokens, category: list[0].code, run: Date.now().toString(36) };
}

function auth(data) {
  const token = data.tokens[exec.scenario.iterationInTest % data.tokens.length];
  return { headers: { ...BASE_HEADERS, Authorization: `Bearer ${token}` } };
}

export function login() {
  const i = 100 + exec.scenario.iterationInTest; // accounts not used by setup()
  const r = http.post(`${AUTH}/api/v1/auth/login`, JSON.stringify({ phone: phone(i), password: PASSWORD }), json);
  loginTime.add(r.timings.duration);
  check(r, { "login 200": (x) => x.status === 200 });
}

export function browse(data) {
  const p = auth(data);
  const list = http.get(`${API}/api/v1/requests?page_size=20`, p);
  check(list, { "list 200": (x) => x.status === 200 });
  const rows = list.status === 200 ? list.json("results") : [];
  if (rows.length) {
    const one = http.get(`${API}/api/v1/requests/${rows[0].id}`, p);
    check(one, { "detail 200": (x) => x.status === 200 });
  }
}

export function submit(data) {
  const p = auth(data);
  const n = exec.scenario.iterationInTest;
  const draft = http.post(
    `${API}/api/v1/requests`,
    JSON.stringify({
      category: data.category,
      title: `Load test ${data.run} request ${n}`,  // unique per run: no duplicate prompt
      description: `Synthetic request ${n} filed during load test run ${data.run}.`,
    }),
    p,
  );
  if (!check(draft, { "draft 201": (x) => x.status === 201 })) return;
  const key = { headers: { ...p.headers, "Idempotency-Key": `load-${exec.vu.idInTest}-${n}-${Date.now()}` } };
  const r = http.post(`${API}/api/v1/requests/${draft.json("id")}/actions/submit`, "{}", key);
  // 429 is the per-user submit limit doing its job when one account files many; count it apart.
  check(r, { "submit 200 or limited": (x) => x.status === 200 || x.status === 429 });
  if (r.status === 200) submitted.add(1);
}
