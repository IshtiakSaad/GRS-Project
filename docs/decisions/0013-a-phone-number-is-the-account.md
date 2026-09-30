# 13. A phone number is the account

**Status:** accepted

## Context

A citizen needs an identity the office can reach. Email is not universal among the people this serves; a national ID number is sensitive, and checking it against the national database is a separate integration with its own approvals. Nearly everyone who will file a request has a mobile number, and SMS reaches every phone ever sold, smart or not.

Phone numbers arrive in every shape: `01712…`, `+8801712…`, `8801712…`, with spaces and dashes, in Bangla digits.

## Decision

One account is one person with their own mobile number. Registration verifies the number by an SMS code; the number is normalised to one form (`+8801XXXXXXXXX`) whichever way it was typed (`apps/common/phone.py`). Someone filing for a family member names them as the beneficiary, with their relation, rather than sharing an account.

Codes are 6 digits, valid for 10 minutes and 5 attempts, at most 3 an hour per phone. They are stored as a keyed HMAC, not with the slow password hasher: six digits have too little entropy for slow hashing to add anything, and the CPU is needed at the 9 a.m. peak. Registering a number that already has an account gives the same answer as a new one, and the real owner gets a warning text, so the form cannot be used to find out who has an account.

If the SMS gateway is down, registration degrades rather than fails: a citizen whose number is not yet verified can still submit one request, and must verify before a second.

The public demo accepts only the unassigned `+880 10` range, and a live deployment refuses that range: no text from the demo can reach a real person, and no test account can exist in production.

## Alternatives considered

- **Email as the account.** The default in most web software, and the wrong default here: many citizens have no email address they check.
- **National ID as the account.** Strong identity, but every login would handle a sensitive number, and a lookup against the national registry is an integration this project cannot assume. It belongs later, as verification attached to a phone account.
- **Several people per number** (a family sharing one phone). Real, but it splits one number's messages between people and blurs who did what in the audit trail. Beneficiaries cover filing for a relative without that cost.

## Consequences

- Losing a phone number means losing the login until the number is recovered or changed; number change is a planned feature ([scope](../scope.md)).
- An SMS outage slows new registrations but does not stop a first request.
- Tests cover each form of number, Bangla digits, the demo/live ranges, the owner warning, and code limits (`test_phone_and_text.py`, `test_register.py`).

## What would change this

An office that must verify identity against the national registry would add that as a step on top of the phone account, not instead of it.
