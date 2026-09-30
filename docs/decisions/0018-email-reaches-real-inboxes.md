# 18. Email reaches real inboxes, and verification mail is capped

**Status:** accepted

## Context

Email is optional here ([decision 13](0013-a-phone-number-is-the-account.md)): a citizen who adds an address gets request updates there too, once the address is confirmed. Confirming means proving the person can read mail sent to it, so the link has to reach that inbox and no other.

Two things pull the other way. Locally and in CI, nothing may ever reach a real person. On the public demo, anyone can register and type any address at all, so a verification email is the one message a stranger can aim at a third party: through us, with our domain on it.

## Decision

- **Locally, Mailpit catches everything.** It delivers nothing and shows every message at `:8025`; the end-to-end test reads the link from it.
- **In production, an SMTP relay delivers for real.** The demo uses Resend's free plan. The app speaks plain SMTP, so the provider is a setting (`EMAIL_HOST`, port, user, key), not code.
- **Production refuses to start misconfigured.** It stops at startup with Mailpit as the relay, a link that is `localhost` or plain http, a placeholder sender, or a relay user with no key. A verification that anyone can complete for any address verifies nothing, and a link to `localhost` in a real inbox opens nothing. Both fail quietly, so neither is allowed to start.
- **Links and the sender follow the domain.** `https://<domain>/verify-email#token=…`, from `Grievance & Service Requests <no-reply@<domain>>`. The token sits in the fragment, so it never reaches a server log.
- **The email looks like what it is.** A text part and an HTML part with one button, one line on why it arrived, one on ignoring it if it was not you, and no bare token.
- **Verification mail is capped.** Three per account a day, and `EMAIL_VERIFY_DAILY_CAP` (60) for the whole site, below the provider's 100, so a flood cannot use up the quota real users need. Both are counted from the outbox in PostgreSQL, so they hold when Redis is down. Request updates go only to addresses already confirmed.

## Alternatives considered

- **One public inbox on the demo** (Mailpit behind a subdomain). No provider, no DNS, nothing to abuse. But it proves only that the sending path works, not that anyone owns the address. It is the right tool locally, and the wrong one anywhere a person is meant to be the reader.
- **Amazon SES.** The cheapest at scale ($0.10 per 1,000), and already the cloud we use. A new account starts in a sandbox that sends only to addresses verified in the console, and leaving it needs a review by AWS. On an account opened after July 2025 there is no SES free tier.
- **Brevo or Mailjet.** More free room (300 and 200 a day). Both are built around marketing email, which is the wrong neighbourhood for a transactional sender's reputation, and more product than this needs.
- **Our own mail server** (Postfix on the instance). No third party sees anything. But EC2 blocks outbound port 25 by default, and a new server's address has no reputation, so the mail would land in spam or bounce.
- **A Gmail account's SMTP.** Common in tutorials. The mail comes from `@gmail.com`, not our domain, so it cannot be authenticated as ours, and Google may stop it without warning.

## Consequences

- A third party, the relay, sees each recipient's address and the message. [Decision 12](0012-texts-carry-no-personal-data.md) is what keeps that harmless: the message is a link and a status, nothing about the request.
- The sending domain needs three DNS records (DKIM, SPF, the bounce MX) and a DMARC policy, and it needs time. A new `.xyz` domain starts with no reputation, so the first messages may land in spam however well they are built. The runbook says what helps.
- The free plan caps sending at 100 a day. The site cap sits below it, so the cap refuses in our words before the provider refuses in its own.
- A misconfigured server does not start. That is louder than sending nothing, which is the point.

## What would change this

A real launch: a government domain with an established reputation, and a relay under a contract with its own terms on where data is processed. Sending past 100 a day: a paid plan, or SES once out of its sandbox. Neither change touches the code.
