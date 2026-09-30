# 12. SMS and email carry a tracking number and a status, nothing personal

**Status:** accepted

## Context

Every status change reaches the citizen by SMS, and by email once they verify an address. An SMS leaves our infrastructure the moment it is sent: it passes through an SMS gateway company, a mobile operator, and ends up on a phone that may be shared with the family or read over someone's shoulder on a bus. Email sits in a third party's mailbox indefinitely. None of these are places a government office controls.

What a citizen writes in a request can be sensitive: a land dispute with a neighbour, a death in the family, a correction to a child's birth record. Officers' comments can be more sensitive still.

## Decision

Outbound messages carry only what the citizen needs to act: a one-time code, a tracking number, what happened ("work has started", "information is needed from you", "resolved"), and an instruction ("log in to reply"). Never a name, a title, a description, a comment or a rejection reason. The details are one login away, behind the citizen's own password.

The rule is enforced where messages are built: templates take a fixed set of fields (`apps/notifications/templates.py`), and tests assert the exact payload stored for an SMS is `{"tracking_no": ...}` and nothing else, including when the trigger was a comment (`test_submit.py`, `test_comments.py`). Texts are Bangla first and written to fit one 70-character Unicode segment where possible. Files stay on object storage the office runs itself, for the same reason.

## Alternatives considered

- **Put the reason in the text** ("rejected: document missing"). More useful at a glance, and the most requested thing in any notification system. Rejected: a rejection reason reveals what the request was about, and a text is the least private place it could go.
- **Send a link that opens the request directly.** Saves a step, but a link in a text is also what every phishing message looks like, and training citizens to tap links in texts that claim to come from a government office works against them. The text says "log in"; the citizen goes to the site they know.

## Consequences

- A leaked, forwarded or shoulder-read text reveals that a request exists and its status, nothing more.
- The companies that carry the messages (the SMS gateway, and the mail relay of [decision 18](0018-email-reaches-real-inboxes.md)) see a phone number or an address and that same status, nothing more.
- The citizen has to log in to learn more. On a shared phone that is the point.
- The texts are short enough to fit one segment, which also keeps the SMS bill down.

## What would change this

A citizen opting in, per request, to fuller texts. That would be their choice about their own data, recorded as such; the default would stay as it is.
