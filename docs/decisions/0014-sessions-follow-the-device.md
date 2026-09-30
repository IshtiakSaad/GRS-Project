# 14. How long a login lasts depends on whose device it is

**Status:** accepted

## Context

Many citizens file from a computer that is not theirs: at a Union Digital Centre, a cyber café, a relative's phone. The next person sits down minutes later. Others file from their own phone and would be annoyed to log in every time. Staff work an office day on an office computer.

Mobile connections also lose responses. When a refresh call's answer is lost, the app retries with the token it still has, which the server has already rotated. Treated naively, that retry looks exactly like a stolen token being replayed.

## Decision

Access tokens last 10 minutes. Refresh tokens are 256 random bits, stored only as a hash, rotated on every use, and grouped into a family per login. Lifetimes (idle, absolute) depend on a trust mode:

| Mode | Who | Idle | At most |
|---|---|---|---|
| Shared (the default for citizens) | A computer that is not theirs | 30 min | 8 h |
| Personal | The citizen said "this is my own phone" | 30 days | 90 days |
| Staff | Officers, whatever they ask for | 4 h | 12 h |
| Administrator | Two-step session | 30 min | 8 h |

On a shared device the web app keeps the refresh token for the browser tab only; on a personal one it survives closing the browser.

Presenting a refresh token that was already rotated means it was copied, so the whole family is revoked and the owner is warned by SMS. The exception is the lost response: the successor token is derived from the old one with an HMAC, so for 60 seconds a retry with the old token gets back the same successor instead of setting off the alarm.

Deactivation, role changes and password changes bump a version number that every access token carries, so they take effect within seconds, not at token expiry.

## Alternatives considered

- **One lifetime for everybody.** Either too long for the café or too short for the citizen's own phone.
- **Server sessions with cookies.** Simple and revocable, but the API also serves non-browser clients, and a cookie session on a shared computer has the same problem without the trust choice.
- **No grace window.** Strictly safer against replay, and on 3G it would log real people out every few days for having a bad connection. Sixty seconds of the same answer is a much smaller window than the token's life.

## Consequences

- Citizens on shared devices log in more often. That is the intended cost.
- A refresh token in the browser can be read by script on the page; the Content-Security-Policy, rotation and family revocation limit what a stolen one is worth ([decision 9](0009-static-web-app.md)).
- Tests cover rotation, the grace window, reuse after it, idle versus absolute expiry, and each mode (`test_sessions.py`, `test_login.py`).

## What would change this

Evidence that citizens mostly use their own phones would make personal mode the default and the shared mode the choice, not the other way round.
