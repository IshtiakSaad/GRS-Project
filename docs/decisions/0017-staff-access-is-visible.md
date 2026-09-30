# 17. Every staff look is recorded, and the citizen can see it

**Status:** accepted

## Context

A request holds a citizen's phone number, what they asked for, often a family member's details, and their documents. In any records system the most common privacy breach is not an attacker: it is a member of staff looking up someone they know. The audit log (decision 6) records changes, but reading changes nothing, so it would record nothing.

At the same time, officers make decisions that citizens dislike. A citizen who can see an officer's name can phone them, visit them, or put pressure on them through people they know.

## Decision

Every time staff open a request, change it, download one of its files, or see it on a list page, an access event is written in the same request that did the looking (`apps/audit/access.py`). A list page writes one event naming every request it showed, so browsing a list is as visible as opening each record. If the event cannot be written, the request fails: an unrecorded look is exactly what this exists to prevent. Citizens reading their own requests are not logged; the log watches staff.

The citizen sees their request's log as office, role and time, never a name. Administrators see names.

An officer who needs a request outside their own department (a supervisor, a complaint, a data fix) can open it only by stating a reason from a fixed list, with a written explanation for "other". Those break-glass openings appear in their own report.

Staff lists show the tracking number, category, status, priority, deadline and the citizen's initials: enough to decide what to open, and nothing that makes browsing worthwhile.

## Alternatives considered

- **Log changes only.** Cheaper, and blind to the breach that actually happens.
- **Show the citizen the officer's name.** More transparent on paper. It exposes individual officers to pressure for decisions that are the office's, and it would push officers to avoid difficult requests.
- **Hard walls between departments, no exceptions.** Supervisors and complaints handlers genuinely need to cross them. Break-glass lets them, on the record.

## Consequences

- Every staff read costs one insert. The access log is partitioned by year, like the other log tables, so it stays cheap to write and to query.
- An officer knows every look is recorded, which is most of the protection.
- Tests cover each kind of event, list pages, the citizen's and the auditor's views, and break-glass (`test_access_log.py`).

## What would change this

A regulator's requirement to show citizens officers' names would be a policy decision above this system; the data to do it is already there.
