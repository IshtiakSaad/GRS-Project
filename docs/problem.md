# The problem, before the code

The assignment asks for a service request system: citizens file requests, officers work them, administrators manage categories and see statistics. Read literally, that is a CRUD API with a status column.

We started somewhere else: with the people at each end of a request and the places it can go wrong. This page is what we found and what we decided because of it. Every decision in the code traces back to something here; [traceability.md](traceability.md) walks the chain from each finding to the test that proves the response holds.

---

## Who is on the other end

### The citizen

Salma needs her trade licence renewed. She does not own a laptop. She files from her phone, a four-year-old Android with a cracked corner, on mobile data that drops to 2G when the bus turns off the main road. Or she files from the shared computer at the Union Digital Centre, where the next person sits down in the same chair two minutes after she stands up. She reads Bangla first. When she calls the office to ask what happened, she reads her tracking number aloud to someone writing it on paper.

What that asks of the system:

- **It has to work on a small screen over a bad connection.** The web app is static files, cached forever once fetched. File uploads go straight from the phone to storage, not through the API, so a slow 5 MB scan does not hold a web worker for minutes.
- **A lost response must never cost her a second request.** On 3G the request often arrives and the answer does not; the app retries. Submission takes an `Idempotency-Key`, so the retry gets the original answer. Refreshing a login has a 60-second grace window for the same reason: the new token was sent, the phone never received it, and the retry with the old token is a lost packet, not a thief.
- **The shared computer is the default, not the exception.** A citizen's session lasts 30 minutes idle and 8 hours at most unless she says "this is my own phone", which extends it to 30 and 90 days. Her refresh token is kept only for the browser tab on a shared device.
- **Bangla is the default language,** and every screen, SMS and API error has both. A tracking number or phone number typed with Bangla digits, spaces or no dashes is still understood. The same Bangla word typed on two different keyboards can be two different byte sequences; every text field is normalised (Unicode NFC) so search and duplicate detection see one word, while the zero-width joiners Bangla needs to choose between a conjunct and separate letters are kept. SMS texts are written to fit one Unicode segment (70 characters) where they can, because every extra segment is billed as another message.
- **Her tracking number has to survive being read over the phone.** `26-0000034-2`: the year, a serial, and a Damm check digit. Damm catches every single wrong digit and every swap of two neighbouring digits, which are the two mistakes people make when reading numbers aloud. A mistyped number is refused before any lookup, instead of opening somebody else's request.
- **SMS is the one channel she certainly has.** Not every citizen has email, a smartphone app or data on the day it matters. Every status change reaches her by SMS; email is added once she verifies an address.
- **She may be filing for someone else:** a birth certificate correction for her son, a death certificate for her father. A request can name a beneficiary and their relation to her.

### The officer

Tanvir works in the birth and death registration section. Forty requests are waiting. Some are simple corrections; one is a tangle that will take a morning of phone calls. Someone from his neighbourhood has already called him about their request.

- **He should not choose which request to work next.** If officers pick from a list, the easy and the well-connected get done and the hard ones age. Choosing is also exactly the moment a favour can be asked. He presses one button and gets the most urgent request in his department: priority first, then the nearest deadline, then the oldest. Two officers pressing at the same instant get different requests ([decision 3](decisions/0003-officers-take-the-next-request.md)).
- **He should not be personally exposed.** The citizen sees that "an officer of the Registry section" looked at her request, never his name. Decisions belong to the office. A name on the screen invites a phone call, a visit or worse.
- **His session should fit an office day,** 4 hours idle and 12 at most, whatever the login screen asks for.
- **He should not be lockable.** Five wrong passwords slow the next attempt (1 minute, then 2, 4, 8, capped at 15) rather than locking the account. A lockout would let anyone keep an officer out of work by typing his number with the wrong password. His own known device has its own counter, so an attacker elsewhere cannot slow him down.

### The administrator

The administrator runs the directory (departments, categories, holidays), manages officers, reassigns stuck requests and answers for the numbers.

- **An administrator account is the most valuable one in the system,** so it needs a second factor (TOTP), has recovery codes, and cannot be created through the API at all: the first one is made on the server, with the password read from the terminal ([runbook](runbook.md#first-administrator)).
- **The numbers have to be honest,** because a published number becomes a target. "Resolved on time" is easy to improve by pausing the clock or by rejecting instead of resolving. Every headline statistic is shown beside the figure that would expose it being gamed (below).
- **Someone has to check the decisions,** without reading every one. Every rejection in the last fifth of its deadline goes to a review queue, along with a random 5% of resolutions. An administrator upholds or overturns; nobody reviews their own decision, and the database enforces that.

### The operator

One person looks after the server, part time. They are asleep at 3 a.m. when the disk fills.

- **The system must say when something is wrong, and say nothing otherwise.** Alerts reach a phone. They fire on sustained problems, not on a single bad minute ([decision 10](decisions/0010-alerts-from-the-edge-log.md)).
- **Everything must run from one command on one machine,** with no cloud service required to start it ([decision 8](decisions/0008-one-server-with-compose.md)).
- **Recovery must be practised, not assumed.** A backup nobody has restored is a hope. The restore runs every night and on every push ([decision 11](decisions/0011-continuous-backups-off-the-server.md)).

---

## The ground it runs on

| Condition | What it means for the design |
|---|---|
| Mobile data that drops and reconnects | Every write that matters can be retried safely: idempotent submit, a refresh grace window, idempotent attachment records. Nothing important depends on a response arriving. |
| Carrier-grade NAT: thousands of phones behind one public address | Per-address limits at Nginx are deliberately generous (100 requests/s, 10/s on login routes). The limits that bite are per phone number and per account, in the application ([ratelimit.py](../src/apps/common/ratelimit.py)). |
| Shared devices at Union Digital Centres and cyber cafés | Short sessions by default; long ones only on the citizen's say-so; tokens in tab storage on shared machines. |
| Offices open at 9 a.m., and everyone logs in at once | Password hashing (Argon2id, slow on purpose) runs on its own worker pool, so a login rush cannot starve people already working ([decision 5](decisions/0005-password-hashing-bulkhead.md)). SMS codes are checked with a keyed HMAC, not the password hasher: a 6-digit code gains nothing from slow hashing, and the CPU is needed at 9 a.m. |
| The working week is Sunday to Thursday in Dhaka; holidays are announced, some at short notice; offices close for floods and strikes | Deadlines count working days in Asia/Dhaka, skip holidays and suspension periods, and are recomputed for open requests when an administrator adds one. |
| SMS passes through carriers and gateways outside the government's control | Texts carry a tracking number, a status or a code. Never a name, a description or a comment ([decision 12](decisions/0012-texts-carry-no-personal-data.md)). |
| The SMS gateway will sometimes be down | Registration degrades instead of failing: a citizen whose phone is not yet verified can still file one request, and verify later. |
| Citizens' documents are sensitive | Files stay on object storage the office runs itself, so they can be kept in the country (the public demo runs in Mumbai), and are downloadable only by signed links that expire. |

---

## How offices go wrong, and what the system does about it

None of this assumes bad people. It assumes ordinary pressure: targets, workload, a phone call from someone who knows someone. The system does not try to make misuse impossible. It makes it visible, and it makes the honest path the easy one.

**Cherry-picking.** Officers who choose their work choose the easy and the familiar. *The queue chooses* (claim-next). An administrator can still assign a specific request by hand; every assignment is audited, moving a request from one officer to another takes a written reason, and how often that happens is shown beside each officer's throughput.

**The convenient pause.** Asking the citizen for information stops the deadline clock, which is right: the office cannot act while it waits. It is also the easiest way to look punctual. *An officer may ask twice; a third request needs an administrator.* Time paused and how often information was asked for are shown beside the on-time rate.

**Rejecting to look fast.** A rejection closes a request as surely as a resolution does. *Rejections take a reason from a fixed list.* A rejection in the last 20% of the deadline is reviewed every time. The citizen can reopen a resolved or rejected request within 30 days, twice, and the reopen rate sits beside the resolution time.

**Quietly looking.** A request holds a citizen's personal details. Staff curiosity is the most common privacy leak in any records system. *Every staff read, change and download is recorded,* and so is every list page, naming each request it showed, so browsing through a list is as visible as opening a record. The citizen sees which office looked and when. Opening a request outside one's own department requires a stated reason from a fixed list (supervisor review, citizen complaint, audit, data correction, or other with an explanation), and those break-glass openings have their own report.

**Pressure on a person.** *The citizen sees roles and offices, not names.* Staff lists show a tracking number, category, status, priority, deadline and the citizen's initials: enough to choose what to open, nothing more.

**Rewriting history.** Whoever can change the database can change the log of what happened in it. *The audit log is append-only, hash-chained every minute, and its checkpoints are locked in write-once storage* that the server's own credentials cannot delete. Rewriting rows, re-hashing the chain and fixing the local checkpoints still disagrees with the locked copies ([decision 6](decisions/0006-hash-chained-audit-log.md)).

**Numbers that lie.** Every headline statistic comes with its counterweight:

| Headline | Shown beside it |
|---|---|
| Resolved on time | How often information was asked for, typical time paused, rejections, and rejections close to the deadline |
| Typical days to resolve | How often resolved and rejected requests were reopened |
| Requests per officer | How often requests were moved to someone else |
| Share resolved | How many citizens gave up and withdrew after the deadline |

**Lost messages.** A status change the citizen never hears about is, to her, a change that did not happen. *Notifications are written in the same transaction as the change,* so a committed change always has its message; a crashed queue delays it, it cannot lose it ([decision 2](decisions/0002-notifications-through-an-outbox.md)).

---

## Who might attack it, and how

| Who | Wants to | What stops them |
|---|---|---|
| Someone with a list of phone numbers | Learn which numbers have accounts | Registering an existing number gets the same answer as a new one; the real owner gets an SMS warning (at most one an hour). Wrong password and unknown number look identical, and unknown numbers are delayed on the same schedule. |
| Someone who dislikes an officer | Lock them out | There is no lockout, only a growing delay, and the officer's own device has its own counter. |
| Someone guessing an SMS code | Take over a registration | 5 attempts per code, 10 minutes per code, 3 codes an hour per phone. |
| The next person at a shared computer | Use the last person's session | Short sessions by default; refresh tokens rotate, and presenting an old one ends every session of the account and warns the owner by SMS. |
| Someone with a stolen admin password | Run the system | A second factor (TOTP) on every admin session; enrolling one needs a fresh login, not just a stolen token. |
| Someone uploading a crafted file | Reach an officer's machine | Nothing is downloadable until ClamAV has scanned it and its real type has been read from its bytes. A PDF label on an executable is refused. If the scanner is down, files wait. |
| A flood of requests | Take the site down | Nginx limits per address, the application per phone and per account. Login routes have their own, tighter limit and their own worker pool. |
| A botnet trying a different number from each address | Make logging in slow for everyone | Only partly stopped. Each address stays under its limit and no account builds up a delay, so every attempt costs a hash. The damage stops at the login pool: people already in keep working. Stopping the flood itself needs filtering in front of the server ([decision 5](decisions/0005-password-hashing-bulkhead.md)). |
| Someone with a list of other people's email addresses | Send them mail from a government domain | Only a confirmation email can go to an unconfirmed address: three per account a day, a daily cap for the site, and nothing in it but a button ([decision 18](decisions/0018-email-reaches-real-inboxes.md)). Request updates go only to confirmed addresses. |
| An insider with database access | Change a record and the trail | Separate database roles; the application's role cannot alter the schema, the log tables or the checkpoints. Every statement from a personal operator login is recorded by pgaudit. |
| Root on the server | Rewrite history cleanly | The checkpoints the chain is verified against are outside the server, locked. |

---

## What we assumed

Some things could not be measured from here. We designed for these, and we write them down so they can be checked.

| Assumption | If it turns out wrong |
|---|---|
| Most citizens reach the service on an Android phone with a browser, often a shared one | If many have only basic feature phones, the next channel is filing at a counter on the citizen's behalf, with the citizen confirming by SMS. The data model already allows it: a request records who filed it separately from whose it is. |
| SMS arrives within minutes nearly always | A second provider behind the same interface, with failover. The code already talks to SMS through one provider interface. |
| Each person has their own phone number, and one account per number is right | Families sharing one phone would need several people under one number. We chose one person, one number, and named beneficiaries for filing on someone's behalf. |
| Staff are mostly honest, and misuse comes from pressure rather than intent | The trail is already complete. A stricter office would add a two-person rule for sensitive administrator actions. |
| One server is enough for a district's volume | Measured: about 70–85 requests a second on 2 vCPUs with no errors, and graceful slowing beyond that. The path out is more API replicas, then the database on its own host ([architecture](architecture.md#scaling-path)). |

---

## What "done" meant

We held ourselves to one rule: **every claim in these documents is proven by something that runs.** A test, a load test, a chaos run or a restore drill. If we could not prove something to that standard, it did not ship, and [scope.md](scope.md) says what was left out and why.
