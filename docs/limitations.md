# Limitations

What this build does not do, does not prove, or does badly. Each one is stated with why it is so, what it costs, and what would lift it. Nothing here is hidden elsewhere: where a limit was a choice, the decision record that made it is linked.

The [scope](scope.md) lists features left out on purpose. This page is wider: it also covers what the demo cannot show, where the defences stop, and how far the evidence reaches.

---

## 1. The live demo runs in demo mode

`https://grs.root-access.xyz` is a real deployment (a real server, domain, TLS certificate, email relay and off-site backups) with one switch on: `DEMO_MODE=true`. That switch changes what the site accepts.

| Limitation | Why | What it costs | What lifts it |
|---|---|---|---|
| **Only numbers starting with 010 are accepted.** A real Bangladeshi number (013–019) is refused, and the screen says so. | There is no SMS provider on the demo. Codes are shown on screen instead, in a demo inbox anyone can open. With real numbers allowed, anyone could type a stranger's number and read their codes. 010 is a prefix no operator uses. | A reviewer cannot sign up with their own phone. | An SMS provider (paid per message, and a Bangladeshi sender ID needs approval). Then `DEMO_MODE=false`, and every operator's numbers work; the code already accepts them ([decision 13](decisions/0013-a-phone-number-is-the-account.md)). |
| **No SMS is sent at all.** | As above: $0 budget, no provider. | The SMS path is proven against a fake provider, not a real gateway. Delivery times, failures and costs of a real gateway are unmeasured. | A provider contract. The code talks to SMS through one interface. |
| **A demo account proves nothing about who holds the number.** | Anyone can read any demo code. | On the demo, verification shows the flow works, not that it verifies anything. | A real gateway: then a code proves the person can read texts sent to that number. |
| **Anyone can log in to the demo citizen and officer accounts, and change their passwords.** | Their passwords are published, so reviewers can try every role. | One visitor can lock the next reviewer out of an account until the nightly reset. | Protecting the seeded accounts from password, two-step and activation changes while in demo mode. Not built. |
| **The demo administrator's second step is a fixed, published code: `123456`.** | Reviewers must reach the administrator's screens without an authenticator app. The step still runs (with its delay after failures and its audit), but a published code proves nothing, so on the demo the administrator is protected by nothing but a published password. Only the seeded demo administrator accepts it, only in demo mode; a live deployment refuses that account's 010 number and has no such code (tested). | Anyone can act as the demo administrator until the nightly reset. | Real two-step login, which every other administrator already has. |
| **Everything is wiped at 03:00 Dhaka time.** | The demo must start clean each day. | Anything a reviewer creates is gone the next morning. The administrator's two-step key is kept; recovery codes are not. | Not needed outside the demo. |
| **Email: 100 messages a day, and it may land in spam.** | Resend's free plan. The domain is new and has no sending reputation. | The site allows 60 verification emails a day and 3 per account ([decision 18](decisions/0018-email-reaches-real-inboxes.md)). | A paid plan, and a government domain with years of reputation. |

---

## 2. Identity

| Limitation | Why | What it costs | What lifts it |
|---|---|---|---|
| **No national ID check.** The name on an account is whatever was typed. | A lookup against the national registry is an integration with its own approvals, and every login would then handle a sensitive number. | The system knows a phone, not a person. | An agreement with the registry, added as a verification step on top of the phone account ([scope](scope.md)). |
| **One person can hold several accounts.** | Many people carry two or three SIMs, and one account per number was the rule. | Per-account limits can be multiplied by owning more SIMs. | The ID check above. |
| **A phone number cannot be changed.** | Changing it safely needs both numbers verified, or an identity check at an office when the old one is lost. That is a procedure first. | A lost number means a lost login. | An office procedure for lost numbers. |
| **A number unused for 180 days gets no reset code.** | Operators reissue dormant numbers (SIM recycling), so the code might reach a stranger. | Its owner must go to a help desk with their ID, and that desk procedure does not exist yet. | The same office procedure. |
| **Families sharing one phone need one account per person**, or one account naming the others as beneficiaries. | One person, one number keeps the audit trail clear. | Awkward for a shared family phone. | A decision by the office, not code. |

---

## 3. Security: where the defences stop

| Limitation | Detail | What lifts it |
|---|---|---|
| **A botnet can make logging in slow for everyone.** | Each address stays under the edge limit; each attempt names a different phone, so no account builds up a delay; and every attempt costs a password hash (about 23 ms of CPU on the server). Two `api-auth` workers top out near 85 attempts a second (a calculation from that cost, not a measurement). People already logged in are unaffected ([decision 5](decisions/0005-password-hashing-bulkhead.md)). | Filtering in front of the server (a DDoS service) and a challenge on the login form that appears only during a flood. Both need a provider account. |
| **Someone can pause SMS codes for everyone for up to an hour.** | The site's hourly budget of codes (300) stops someone paying our SMS bill by asking for codes to thousands of numbers. The price: once spent, new sign-ups and resets wait for the hour to roll on. | The same filtering; a larger budget sized to real traffic. |
| **Per-address limits are generous on purpose.** | Thousands of phones share one address behind carrier NAT, so Nginx allows 100 requests a second per address (10 on login routes). One address can do a lot before it is stopped. | Nothing, without knowing more about the caller. The limits that bite are per phone and per account. |
| **The off-site locks can be removed by the AWS account holder.** | Audit checkpoints and WAL are locked in GOVERNANCE mode for 7 days, so the demo account can be closed afterwards. GOVERNANCE lets an account holder with a separate permission delete early; COMPLIANCE lets nobody. | COMPLIANCE mode, for years, in a real deployment (a setting). |
| **Secrets sit in a `.env` file on the server.** | One server, no secrets manager. Anyone with root there can read the database passwords, signing keys and the email key. The AWS role has no stored key. | A secrets manager, and fewer people with root. |
| **No independent security review or penetration test.** | Out of reach for this project. | An external test before a public launch. |
| **The web app allows inline scripts** (`'unsafe-inline'` in the Content Security Policy). | Next.js inlines small bootstrap scripts. | Nonces or hashes for the inline scripts. |
| **One administrator can do everything an administrator can.** | A two-person rule means little with one administrator. Every change is audited with the value it replaced. | A two-person rule once an office has several administrators ([scope](scope.md)). |

---

## 4. Availability and scale

| Limitation | Detail | What lifts it |
|---|---|---|
| **One server in one data centre.** | If the EC2 instance or its zone fails, the site is down until it is rebuilt ([decision 8](decisions/0008-one-server-with-compose.md)). | The scaling path in [architecture](architecture.md#scaling-path): API replicas, the database on its own host, a standby in another zone. |
| **Up to about a minute of data can be lost** with the server. | WAL is shipped off the host at least every 60 seconds (`archive_timeout = 60`). | A streaming standby on a second host brings it to seconds. The standby profile exists, off by default. |
| **Rebuilding after losing the whole server has not been timed.** | Restoring the database to a chosen moment from the off-site bucket is drilled every night and takes seconds at demo size. Provisioning a new server, restoring, and moving DNS end to end has not been rehearsed. | A timed disaster-recovery rehearsal. |
| **The measured ceiling is 70–85 requests a second** on 2 vCPUs. | Beyond it, responses slow down (p95 8–11 s at double the load) without failing. The scaling path is designed, not tested: no run with several API replicas. | A load test on a multi-host setup. |
| **Deploys restart the application.** | Each deploy waits for the new build to report healthy and rolls back if it does not, but containers restart. How many requests fail during that window has not been measured. | A second application host, and a rolling deploy. |
| **The public IP address is not fixed.** | No Elastic IP ($0 budget). Stopping the instance changes the address, and DNS must be updated. | An Elastic IP. |
| **Email and SMS each have one provider.** | Messages wait in the outbox during an outage and are delivered after it, but no second provider takes over. | A second provider behind the same interface ([scope](scope.md)). |

---

## 5. The citizen's experience

| Limitation | Detail | What lifts it |
|---|---|---|
| **The first visit is heavy on 2G.** | Opening any page for the first time downloads about 199 KB (gzipped), almost all of it the framework every page shares. That is about 16 s at 100 kbps (2G/EDGE) and 4 s at 400 kbps, counting transfer only. Each later page adds 2–10 KB. Measured by `tools/measure_page_weight.py`. | A lighter first page (server-rendered HTML with no framework for the landing and tracking pages), or a service worker ([scope](scope.md)). |
| **No offline drafts.** | A draft lost to a dropped connection must be retyped. Submission itself is safe to retry. | A service worker with conflict handling. |
| **No channel for feature phones.** | There is no USSD, IVR or SMS filing, and assisted filing at a counter is not built. | Assisted submission, once an office defines the procedure ([scope](scope.md)). |
| **Accessibility has not been audited.** | No WCAG audit, and no test with a screen reader. | An audit and fixes. |
| **The Bangla has not been reviewed by a professional translator** or tested with citizens. | Written by the team. | A language review and a test with real users. |
| **Every person described in the [problem](problem.md) is an assumption.** | No interviews with citizens, officers or administrators. The design follows from stated assumptions, which are listed so they can be checked. | User research in one office. |

---

## 6. The office

| Limitation | Detail | What lifts it |
|---|---|---|
| **The counterweights beside each statistic are for a person to judge.** | No threshold says when a number is suspicious; no real data was available to set one ([decision 16](decisions/0016-every-statistic-has-a-counterweight.md)). | A few months of real data, and thresholds agreed with the office. |
| **The review sample (5% of resolutions) is a guess.** | Late rejections are always reviewed; the random share has no data behind it. | Adjust from what reviews find. |
| **Holidays and office closures are entered by hand.** | No feed of government holidays. | An official calendar feed. |
| **Public statistics are not published.** | Small counts identify people. | Suppression thresholds agreed with the office ([scope](scope.md)). |

---

## 7. How far the evidence reaches

Every claim in these documents is proven by something that runs, but each proof has edges. The [evaluation](evaluation.md) states them in full; in short:

- **The load tests ran once each**, on 28 September 2026, with the load generator on the same two-CPU machine as the application. The workload mix was designed by us, not recorded from real traffic.
- **96% line coverage** says which lines ran, not that every behaviour was checked. No branch coverage target and no mutation testing.
- **Browser tests run on Chromium only**, emulating a Pixel 7 screen. No Safari, no Firefox, no real phones, no throttled network.
- **The check-digit study uses the error classes of English-language research** (Verhoeff, 1969). How people misread Bangla digits aloud was not studied.
- **Timing figures come from two machines:** the live EC2 instance (load tests, restore) and a laptop (hash cost, suite time). They are labelled where they appear.
