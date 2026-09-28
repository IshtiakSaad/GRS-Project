// Steady filing of requests while chaos.sh stops and restarts the task broker.
// Every submission must still succeed: the notification is a row in PostgreSQL (the outbox),
// and the broker only makes delivery fast.

import { setup as stormSetup, submit as stormSubmit } from "./storm.js";

export const options = {
  scenarios: {
    submit: {
      executor: "constant-arrival-rate",
      exec: "submit",
      rate: parseInt(__ENV.RATE || "4"),
      timeUnit: "1s",
      duration: __ENV.DURATION || "100s",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  thresholds: {
    "http_req_failed{scenario:submit}": ["rate<0.01"],
    checks: ["rate>0.99"],
  },
};

export const setup = stormSetup;
export const submit = stormSubmit;
