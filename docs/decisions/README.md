# Decisions

Each record follows one choice that shapes the system. It covers what forced the choice, what we decided, the alternatives we rejected and why, what the choice costs, and what would make us change it. Most start from a finding in [the problem](../problem.md).

**The data and its rules**

| # | Decision |
|---|---|
| 1 | [PostgreSQL enforces the rules, not only the application](0001-postgresql-enforces-the-rules.md) |
| 6 | [The audit log is append-only and hash-chained](0006-hash-chained-audit-log.md) |
| 11 | [Backups are continuous and leave the server](0011-continuous-backups-off-the-server.md) |

**People and fairness**

| # | Decision |
|---|---|
| 3 | [Officers take the next request; they do not choose](0003-officers-take-the-next-request.md) |
| 16 | [Every statistic is shown beside the number that would expose it being gamed](0016-every-statistic-has-a-counterweight.md) |
| 17 | [Every staff look is recorded, and the citizen can see it](0017-staff-access-is-visible.md) |

**The citizen's phone, network and language**

| # | Decision |
|---|---|
| 12 | [SMS and email carry a tracking number and a status, nothing personal](0012-texts-carry-no-personal-data.md) |
| 13 | [A phone number is the account](0013-a-phone-number-is-the-account.md) |
| 14 | [How long a login lasts depends on whose device it is](0014-sessions-follow-the-device.md) |
| 15 | [Tracking numbers are made to be read aloud](0015-tracking-numbers-are-read-aloud.md) |
| 18 | [Email reaches real inboxes, and verification mail is capped](0018-email-reaches-real-inboxes.md) |
| 7 | [Files go straight to object storage and are checked afterwards](0007-uploads-go-straight-to-storage.md) |
| 9 | [The web app is static files served by the same Nginx](0009-static-web-app.md) |

**Staying up**

| # | Decision |
|---|---|
| 2 | [Notifications go through an outbox table](0002-notifications-through-an-outbox.md) |
| 4 | [Two Redis instances, split by how they may fail](0004-two-redis-instances.md) |
| 5 | [Password hashing runs on its own worker pool](0005-password-hashing-bulkhead.md) |
| 8 | [One server with Docker Compose, not Kubernetes](0008-one-server-with-compose.md) |
| 10 | [Service levels are measured from Nginx's log, and alerts go to a phone](0010-alerts-from-the-edge-log.md) |
