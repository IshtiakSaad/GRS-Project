# 13. A phone number is the account

**Status:** accepted

## Context

A citizen needs an identity the office can reach. Email is not universal among the people this serves; a national ID number is sensitive, and checking it against the national database is a separate integration with its own approvals. Nearly everyone who will file a request has a mobile number, and SMS reaches every phone ever sold, smart or not.

Phone numbers arrive in every shape: `01712…`, `+8801712…`, `8801712…`, with spaces and dashes, in Bangla digits.

## Decision

One account is one person with their own mobile number. Registration verifies the number by an SMS code; the number is normalised to one form (`+8801XXXXXXXXX`) whichever way it was typed (`apps/common/phone.py`). Someone filing for a family member names them as the beneficiary, with their relation, rather than sharing an account.

Codes are 6 digits, valid for 10 minutes and 5 attempts, at most 3 an hour per phone. They are stored as a keyed HMAC, not with the slow password hasher: six digits have too little entropy for slow hashing to add anything, and the CPU is needed at the 9 a.m. peak. Registering a number that already has an account gives the same answer as a new one, and the real owner gets a warning text, so the form cannot be used to find out who has an account.

A correct code logs the new citizen in. It reaches the phone a minute after its owner chose the password, so asking for the password again proves nothing more; it only costs a screen on a slow connection. A citizen already logged in (confirming later from the profile) keeps the session they have.

Staff do not register. An administrator adds an officer, and the officer's phone gets a text that says what happened and links to a page that sets the password, with the number already filled in and a code valid for 24 hours: a new officer may read it after lunch. No one but the officer ever chooses the password. An administrator's reset sends the same kind of text.

The per-phone limit does nothing against someone who asks for codes to thousands of different numbers. Each text is paid for, and in the fraud known as SMS pumping the attacker takes a share of the fee through a complicit operator. So the whole site has an hourly budget of codes (`SMS_CODES_HOURLY_CAP`), sized above the busiest real hour. Once it is spent, register, resend and reset answer `429` for everyone until the hour rolls on. They check it before looking up the number, so the refusal says nothing about who is registered.

If the SMS gateway is down, registration degrades rather than fails: a citizen whose number is not yet verified can still submit one request, and must verify before a second.

The public demo accepts only the unassigned `+880 10` range, and a live deployment refuses that range: no text from the demo can reach a real person, and no test account can exist in production.

## Alternatives considered

- **Email as the account.** The default in most web software, and the wrong default here: many citizens have no email address they check.
- **National ID as the account.** Strong identity, but every login would handle a sensitive number, and a lookup against the national registry is an integration this project cannot assume. It belongs later, as verification attached to a phone account.
- **A limit per address on sign-ups**, against SMS pumping. Thousands of real phones reach us from one mobile operator's address (carrier NAT), so a limit tight enough to matter would turn away a district. The site budget caps the cost without guessing who is who.
- **A challenge (CAPTCHA) on the sign-up form.** It stops scripts, and it costs every citizen on 2G a heavy third-party script and a puzzle in a language that may not be theirs. It belongs as a switch that turns on only while an attack is under way, which needs a provider account.
- **Sending staff to "Forgot password".** The first version did this. A new officer got a bare code, and the page they had to find said "Password changed" about a password they never had.
- **Several people per number** (a family sharing one phone). Real, but it splits one number's messages between people and blurs who did what in the audit trail. Beneficiaries cover filing for a relative without that cost.

## Consequences

- Losing a phone number means losing the login until the number is recovered or changed; number change is a planned feature ([scope](../scope.md)).
- An SMS outage slows new registrations but does not stop a first request.
- Someone who spends the hourly budget pauses codes for every new citizen for up to an hour. That is the smaller harm: the alternative is paying for their texts with no limit.
- A staff code lives 24 hours instead of 10 minutes. Five attempts still bound the guessing, and the text goes only to the officer's own phone.
- Tests cover each form of number, Bangla digits, the demo/live ranges, the owner warning, code limits, the site budget, logging in with the code, and the staff welcome text (`test_phone_and_text.py`, `test_register.py`, `admin/test_users.py`).

## What this does not prove

- **That the person holds the number, on the demo.** On a real gateway, the code proves the person can read texts to that number. The demo sends nothing: anyone can read any demo code in the demo inbox, so the demo proves the flow, not the ownership.
- **Who the person is.** No national ID is checked. Anyone with a phone can open an account in any name, and the name is what they typed.
- **That one person has one account.** Many people carry two or three SIMs, and each number can hold an account.

These are limits of v1, not bugs. The phone check is one every citizen can pass; identity comes from the national registry, and that is an integration with its own approvals ([scope](../scope.md)).

## What would change this

An office that must verify identity against the national registry would add that as a step on top of the phone account, not instead of it.
