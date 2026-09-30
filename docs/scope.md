# Scope

## The rule

Version 1 is the smallest system in which every claim is proven by something that runs: a test, a load test, a chaos run or a restore drill. Where a feature could not be built *and* proven to that standard, we left it out and prepared the ground for it instead: a column, a constraint, an interface. A system that does fewer things and can show that each of them holds is worth more to an office than one that does more and hopes.

## What v1 is

The assignment's requirements in full, plus what we found a real office would need on day one ([problem.md](problem.md)):

- **For citizens:** phone registration verified by SMS; Bangla first; retries that never duplicate a request; tracking numbers that survive being read aloud; SMS on every status change; attachments; a timeline; reopening within 30 days; seeing which office looked at their request.
- **For officers:** a queue that chooses for them; asking the citizen for information with the clock paused; internal notes the citizen never sees; break-glass access outside their department, on the record.
- **For administrators:** two-step login; the directory, holidays and office closures; creating and deactivating officers; assigning and reassigning; a review queue for late rejections and a sample of resolutions; statistics shown with their counterweights.
- **For whoever runs it:** one command to start it anywhere; health-checked deploys that roll themselves back; alerts on a phone; continuous backups off the server and a restore drill every night; an audit trail that root on the server cannot rewrite unnoticed.

## Left out on purpose

| Not in v1 | Why | Already in place | What brings it in |
|---|---|---|---|
| **Assisted submission** (an officer files at the counter for a citizen, who confirms by SMS) | The code is small; the controls are the work. Who at the counter may file, how the citizen confirms, and what stops an officer filing requests in other people's names to lift their own numbers are procedure questions for an office to answer first. | The data model records who filed a request separately from whose it is, with constraints and indexes to spot unusual filing patterns. The endpoint refuses it until the procedure exists. | An office defining the procedure |
| **Offline drafts** and a lighter first load for 2G | The failure that actually costs citizens on a bad connection is a lost *response*, and that is solved (idempotent submit, refresh grace window). A lost draft costs retyping a paragraph. Offline drafts need a service worker and conflict handling: real complexity for the smaller problem. | Static, cached pages; small bundles; direct uploads | Measured drop-off on 2G |
| **Re-encoding uploaded images** | Every file is already scanned by ClamAV and its real type read from its bytes, which covers the dangerous files. Re-encoding would strip location and device metadata from phone photos, which is a privacy gain, but it also changes evidence documents, and how much quality a scanned deed may lose is a decision for the office, not a default we should guess. | The verification step that re-encoding would join | An agreed quality level for scanned documents |
| **In-app notification inbox**, and merging repeated texts | SMS reaches every citizen; an inbox reaches only those who open the app, and the request's timeline already shows every change. A request changes status a handful of times, so repeated texts are rare. | Notification columns and indexes for an inbox; status texts expire after 72 hours so a delayed one is never sent late | A majority of citizens using the app regularly |
| **Changing a phone number** | The number is the account ([decision 13](decisions/0013-a-phone-number-is-the-account.md)). Changing it safely needs both numbers verified, or, when the old one is lost, an identity check at an office. That is a procedure first. | Token versions, which already end every session within seconds when a password or role changes | An office procedure for lost numbers |
| **Checking identity against the national ID registry** | An account proves a phone, not a person: the name is what the citizen typed, and one person with three SIMs can hold three accounts. A registry lookup is an integration with its own approvals, and every login would then handle a sensitive number ([decision 13](decisions/0013-a-phone-number-is-the-account.md)). | Beneficiaries and relations on requests; an audit trail of who filed what | An agreement with the registry |
| **A two-person rule for sensitive administrator actions** | Meaningful only with several administrators. Every administrator change is already audited with the value it replaced. | The audit trail it would build on | Several administrators per office |
| **A second SMS provider with failover** | Needs a second contract. The system already survives an SMS outage: messages wait in the outbox and are delivered when the provider returns, and registration degrades instead of failing. | One provider interface; the outbox; retries with backoff | A second provider |
| **Public anonymised statistics** | Small counts identify people ("the one rejected land request in this union this month"). Publishing safely needs suppression thresholds agreed with the office. | Statistics with counterweights for administrators ([decision 16](decisions/0016-every-statistic-has-a-counterweight.md)) | Agreed thresholds |
| **Zero-downtime deploys** | One server, deploys at quiet hours. What matters more is that a bad deploy never stays: every deploy waits for the new build to report healthy through TLS and rolls back on its own if it does not. | Health-checked deploys with automatic rollback; additive migrations | A second application host |

## Deliberately manual

Some things are left to people on purpose, not for lack of time.

- **Promoting the database standby.** Automatic failover on one network is how a system ends up with two primaries accepting different writes. Two people agree, the old primary is stopped, then the standby is promoted ([runbook](runbook.md#standby)).
- **Overturning a decision.** The review queue flags; an administrator decides. The system never reverses an officer on its own.
- **Spotting gaming in the statistics.** The numbers are shown side by side for a person to judge, not turned into automatic accusations ([decision 16](decisions/0016-every-statistic-has-a-counterweight.md)).

## If we had the next month

In this order, because each one is a step toward serving citizens who cannot use the web app today:

1. Assisted submission, once an office defines the procedure: it reaches citizens without a smartphone.
2. Image re-encoding, with a quality level agreed for documents.
3. Phone number change, with the office procedure behind it.
4. A second SMS provider.
5. Public statistics with suppression thresholds.
