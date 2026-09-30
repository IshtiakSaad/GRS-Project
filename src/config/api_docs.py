"""What the API reference at /api/docs/ says before the first endpoint: how to start, the rules
every endpoint follows, and the order a reader meets the endpoints in (a request's life)."""

DESCRIPTION = """
Citizens file service requests with government offices, officers work through them in order,
and administrators run the whole thing. Every endpoint below can be tried from this page.

## Start here

1. **Log in.** `POST /api/v1/auth/login` with a phone number and password. On the public
   demo every account's password is `demo-password-2026`:
   - citizens `+8801000000101` to `+8801000000104`
   - officers `+8801000000011` to `+8801000000014`
   - the administrator `+8801000000001`, who also needs a two-step code

2. **Use the token.** Copy `access` from the answer into the **Bearer** field under
   Authentication on this page. Every call you try after that is made as that user.
3. **Administrators take one more step.** Their login answers `mfa_required: true` with an
   `mfa_token`; send it with the 6-digit code from an authenticator app to
   `POST /api/v1/auth/2fa/verify`.
4. **Read the texts.** Nothing is really sent on the demo. What the system would text a
   number is at `GET /api/v1/demo/sms/{phone}`.

Access tokens last 10 minutes. `POST /api/v1/auth/token/refresh` swaps the refresh token for a
new pair; each refresh token works once, and presenting a used one ends every session of the
account.

## A request's life

Draft (`POST /requests`) → submit (`…/actions/submit`, with an `Idempotency-Key`) → an officer
takes the next one (`POST /queue/claim-next`) → `start` → maybe `request_info`, which pauses the
deadline until the citizen answers with a comment → `resolve` or `reject`. The citizen can
track it by number, read its timeline, see which office looked at it, and reopen it within
30 days.

## Rules every endpoint follows

**Errors** have one shape, whatever went wrong:

```json
{"error": {"code": "INVALID_TRANSITION", "message": "…", "fields": {}, "request_id": "…"}}
```

`code` is stable and meant for programs; `message` is for people, in their language. Quote
`request_id` when reporting a problem: every log line of that request carries it.

**Language.** English by default; send `Accept-Language: bn` for Bangla. The web app sends
the visitor's language, so citizens see Bangla there.

**Retries are safe where it matters.** Submitting takes an `Idempotency-Key` header: 8 to 64
letters, digits, `-` or `_`, new for each request, such as a UUID. Sending the same key again
returns the first answer and files nothing new; the same key with a different body is refused
with `422`.

**Edits need the current version.** Drafts and priority are changed with `If-Match` set to
the `ETag` from the last read. Without it: `428`. If someone changed it since: `412`; reload
and try again.

**Limits.** Too many calls answer `429` with a `Retry-After` header in seconds. The limits
that matter are per phone number and per account, not per address: thousands of phones can
share one address behind a mobile operator.

**Numbers are forgiving.** Phone numbers are accepted in any common form (`017…`, `+88017…`,
with spaces or Bangla digits). Tracking numbers like `26-0000042-7` carry a check digit: a
mistyped one is refused before anything is looked up.

**Lists** are paged by cursor: follow `next` until it is `null`. Page 500 is as fast as page 1.

**Times** are ISO 8601 in UTC. Deadlines are counted in Dhaka working days.
"""

# Each tag's display name and what it holds, in the order a reader should meet them.
TAGS = [
    {
        "name": "auth",
        "x-displayName": "Log in and register",
        "description": "Accounts are phone numbers, verified by SMS code. Administrators log "
        "in with a second step.",
    },
    {
        "name": "me",
        "x-displayName": "Your account",
        "description": "Profile, password, and the sessions open on other devices.",
    },
    {
        "name": "requests",
        "x-displayName": "Requests",
        "description": "Draft, submit, track and act on a request. After submission a request "
        "changes only through its actions, and each action is allowed only to the right "
        "person in the right state.",
    },
    {
        "name": "queue",
        "x-displayName": "Officer queue",
        "description": "Officers do not choose their cases: `claim-next` gives the most "
        "urgent request in their department, and two officers never get the same one.",
    },
    {
        "name": "comments and files",
        "x-displayName": "Comments and files",
        "description": "Public comments and internal notes; files go straight to storage by "
        "signed URL and are scanned before anyone can download them.",
    },
    {
        "name": "transparency",
        "x-displayName": "Who looked",
        "description": "Every time staff open a request is recorded. Citizens see which "
        "office looked; administrators see who.",
    },
    {
        "name": "admin",
        "x-displayName": "Administration",
        "description": "Departments, services, holidays, office closures, officers, the "
        "review queue and statistics. Needs a two-step session.",
    },
    {
        "name": "demo",
        "x-displayName": "Demo inbox",
        "description": "The public demo's stand-in for real SMS. Absent in production.",
    },
]

TAG_GROUPS = [
    {"name": "Getting in", "tags": ["auth", "me"]},
    {"name": "Requests", "tags": ["requests", "queue", "comments and files", "transparency"]},
    {"name": "Running the office", "tags": ["admin"]},
    {"name": "Demo", "tags": ["demo"]},
]

# A plain title for every operation, so the reference reads "Take the next request" instead of
# a path. A test fails if an endpoint is added without one.
SUMMARIES = {
    "POST /api/v1/auth/register": "Register with a phone number",
    "POST /api/v1/auth/otp/verify": "Confirm the number with the SMS code",
    "POST /api/v1/auth/otp/resend": "Send the SMS code again",
    "POST /api/v1/auth/login": "Log in",
    "POST /api/v1/auth/2fa/verify": "Second step: authenticator code",
    "POST /api/v1/auth/2fa/recovery": "Second step: recovery code",
    "POST /api/v1/auth/2fa/setup": "Start setting up two-step login",
    "POST /api/v1/auth/2fa/confirm": "Finish setting up two-step login",
    "POST /api/v1/auth/token/refresh": "Get new tokens",
    "POST /api/v1/auth/logout": "Log out",
    "POST /api/v1/auth/password/reset/request": "Ask for a password reset code",
    "POST /api/v1/auth/password/reset/confirm": "Set a new password with the reset code",
    "POST /api/v1/auth/email/verify": "Confirm an email address",
    "GET /api/v1/me": "Your profile",
    "PATCH /api/v1/me": "Change your profile",
    "POST /api/v1/me/password": "Change your password",
    "GET /api/v1/me/sessions": "Your open sessions",
    "DELETE /api/v1/me/sessions/{session_id}": "End a session",
    "GET /api/v1/demo/sms/{phone}": "Texts sent to a demo number",
    "GET /api/v1/categories": "Services that can be requested",
    "GET /api/v1/requests": "List requests",
    "POST /api/v1/requests": "Start a draft",
    "GET /api/v1/requests/by-tracking/{number}": "Find a request by tracking number",
    "POST /api/v1/requests/break-glass": "Open a request outside your department",
    "GET /api/v1/requests/{request_id}": "Read a request",
    "PATCH /api/v1/requests/{request_id}": "Edit a draft",
    "DELETE /api/v1/requests/{request_id}": "Discard a draft",
    "POST /api/v1/requests/{request_id}/actions/{action}": "Act on a request (submit, resolve…)",
    "PATCH /api/v1/requests/{request_id}/priority": "Change the priority",
    "GET /api/v1/requests/{request_id}/timeline": "The request's timeline",
    "GET /api/v1/queue": "What is waiting, in the order it will be taken",
    "POST /api/v1/queue/claim-next": "Take the next request",
    "GET /api/v1/requests/{request_id}/comments": "Read the conversation",
    "POST /api/v1/requests/{request_id}/comments": "Add a comment",
    "GET /api/v1/requests/{request_id}/attachments": "List a request's files",
    "POST /api/v1/requests/{request_id}/attachments": "Attach a file: get an upload URL",
    "POST /api/v1/attachments/{attachment_id}/confirm": "Attach a file: confirm the upload",
    "GET /api/v1/attachments/{attachment_id}": "A file's status",
    "GET /api/v1/attachments/{attachment_id}/download": "Download a file",
    "GET /api/v1/requests/{request_id}/access-log": "Who looked at this request",
    "GET /api/v1/admin/departments": "List departments",
    "POST /api/v1/admin/departments": "Add a department",
    "PATCH /api/v1/admin/departments/{code}": "Change a department",
    "GET /api/v1/admin/categories": "List services",
    "POST /api/v1/admin/categories": "Add a service",
    "PATCH /api/v1/admin/categories/{code}": "Change a service",
    "GET /api/v1/admin/holidays": "List holidays",
    "POST /api/v1/admin/holidays": "Add a holiday",
    "DELETE /api/v1/admin/holidays/{day}": "Remove a holiday",
    "GET /api/v1/admin/sla-suspensions": "List office closures",
    "POST /api/v1/admin/sla-suspensions": "Declare an office closure",
    "DELETE /api/v1/admin/sla-suspensions/{id}": "Remove an office closure",
    "GET /api/v1/admin/users": "List accounts",
    "POST /api/v1/admin/users": "Add an officer",
    "GET /api/v1/admin/users/{user_id}": "Read an account",
    "PATCH /api/v1/admin/users/{user_id}": "Change an account",
    "POST /api/v1/admin/users/{user_id}/reset-password": "Reset a staff member's password",
    "GET /api/v1/admin/reviews": "The review queue",
    "POST /api/v1/admin/reviews/{review_id}/decision": "Uphold or overturn a decision",
    "GET /api/v1/admin/stats": "Statistics",
    "GET /api/v1/admin/break-glass": "Break-glass report",
}

# Public views that had no description of their own showed the base class's docstring.
DESCRIPTIONS = {
    "POST /api/v1/auth/otp/verify": "The 6-digit code from the registration text. Five wrong "
    "tries use the code up; ask for a new one.",
    "POST /api/v1/auth/otp/resend": "The same answer whether or not the number has an "
    "account. A cooldown and an hourly cap apply.",
    "POST /api/v1/auth/password/reset/confirm": "The code from the reset text, and the new "
    "password.",
    "POST /api/v1/auth/email/verify": "The token from the link in the verification email.",
}


def add_summaries(result, generator, request, public):
    """drf-spectacular postprocessing hook: titles and missing descriptions from above."""
    for path, operations in result["paths"].items():
        for method, operation in operations.items():
            key = f"{method.upper()} {path}"
            if key in SUMMARIES:
                operation["summary"] = SUMMARIES[key]
            if key in DESCRIPTIONS:
                operation["description"] = DESCRIPTIONS[key]
    return result
