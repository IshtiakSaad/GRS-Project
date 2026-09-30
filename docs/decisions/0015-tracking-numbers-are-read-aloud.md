# 15. Tracking numbers are made to be read aloud

**Status:** accepted

## Context

A tracking number is not only a key. Citizens read it over the phone to an office, write it on paper, type it into a phone with a Bangla keyboard and copy it from an SMS. The two most common mistakes when people copy or read numbers are one wrong digit and two neighbouring digits swapped. A mistyped number that happens to be valid opens someone else's request, or tells a worried citizen that theirs does not exist.

A UUID would be unique, and useless to say out loud.

## Decision

`YY-NNNNNNN-C`, for example `26-0000034-2`: the year of submission in Dhaka time, a serial from that year's database sequence, and a Damm check digit (`apps/service_requests/tracking.py`). Damm catches every single-digit error and every adjacent swap, with one check digit, and needs no letters. Input is accepted with Bangla digits, spaces or no dashes, and the check digit is verified before any database lookup, so a typo gets "that number is not valid" instead of a stranger's request or a false "not found".

Each year has its own sequence, created years ahead, and a missing year is created on the first submission of that year. Past ten million requests in a year the serial widens to eight digits instead of failing. Internally every row has a UUIDv7 as its public id; the tracking number is for people.

## Alternatives considered

- **Luhn** (as on bank cards). Well known, but it misses some adjacent swaps (09 and 90).
- **Verhoeff.** Catches every single error and every neighbour swap, as Damm does. Measured on 5,000 tracking numbers, it also catches more of the rarer mistakes (jump swaps, twins: by 4 to 9 points) and fewer phonetic ones such as 13 heard as 30 (83% against Damm's 98%) ([evaluation](../evaluation.md#8-q6-does-the-tracking-number-catch-the-mistakes-people-make)). We keep Damm: one table and a loop, simpler to implement and to test exhaustively, and better on the class specific to numbers heard over a phone. An earlier version of this record said Verhoeff catches the same errors; the measurement corrected it.
- **Letters and digits** (shorter numbers). Letters are hard to read over a phone line and to type on a Bangla keyboard; `0/O` and `1/I` confusions come back.
- **No check digit.** Every typo becomes a lookup, and some typos become someone else's request.

## Consequences

- Unit tests try every single-digit error and every adjacent swap on real numbers and expect each to be caught (`test_tracking.py`).
- The year prefix tells an officer at a glance how old a request is.
- A refused submission uses no number, so numbers have no gaps to explain (`test_a_refused_submit_uses_no_tracking_number`).

## What would change this

Nothing in the foreseeable volume. A second issuing system (another ministry) would get its own prefix rather than a new format.
