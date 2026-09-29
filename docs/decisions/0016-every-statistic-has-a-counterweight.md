# 16. Every statistic is shown beside the number that would expose it being gamed

**Status:** accepted

## Context

The assignment asks for basic statistics. The moment an office is judged by a number, the number becomes a target, and there are cheap ways to hit each one without serving anyone better:

- **On-time rate** goes up if the clock is paused by asking the citizen for information, or if hard requests are rejected instead of resolved.
- **Time to resolve** goes down if requests are closed quickly and come straight back.
- **Requests per officer** goes up if difficult requests are passed to a colleague.
- **Share resolved** goes up if citizens give up and withdraw.

None of these needs anyone to lie. They are what people do when a number is the goal.

## Decision

Each headline is returned together with its counterweights, from the same filtered set of requests, in one query (`apps/admin_api/stats.py`):

| Headline | Shown beside it |
|---|---|
| Resolved on time | How often information was asked for, typical time paused, rejections, and rejections close to the deadline |
| Typical days to resolve | How often resolved and rejected requests were reopened |
| Requests per officer | How often requests were moved to someone else |
| Share resolved | How many citizens withdrew after the deadline |

The workflow backs the statistics up. An officer can ask for information twice; a third time needs an administrator. Every rejection in the last 20% of the deadline goes to a review queue, with a random 5% of resolutions. Citizens can reopen within 30 days, twice. Periods are chosen in Dhaka dates, so a day's numbers mean that day in Dhaka.

## Alternatives considered

- **Headline numbers only.** What most dashboards do, and what teaches an office to game them.
- **Hide the numbers from the office.** Removes the incentive and the usefulness together.
- **Detect gaming automatically** (flag officers whose pause rate is unusual). Tempting, but it turns statistics into accusations with thresholds nobody can defend yet. Showing the numbers side by side lets a person judge, with context.

## Consequences

- An administrator reading "92% on time" sees, on the same row, whether that came with a high pause rate or many late rejections.
- The statistics are harder to show as a single green number. That is intended.
- Tests check that each headline comes with its counterweights and that an officer's filters can never widen their own scope (`test_stats.py`, `test_reviews.py`, `test_actions.py`).

## What would change this

Published, anonymised statistics for the public would use the same pairing; they are planned, not built ([scope](../scope.md)).
