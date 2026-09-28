# 3. Officers take the next request; they do not choose

**Status:** accepted

## Context

If officers pick requests from a list, two of them can open the same one, and easy or favoured cases get picked first while hard ones age. Choosing a case is also where an officer could be approached to handle a particular citizen's request.

## Decision

`POST /queue/claim-next` gives an officer the most urgent waiting request in their department: highest priority, then oldest. It uses `SELECT … FOR UPDATE SKIP LOCKED`, so officers claiming at the same moment each get a different request and nobody waits on anybody else's transaction. Administrators can still assign or reassign a specific request, with a reason, and it is audited.

## Consequences

- No double handling, no queue contention, no cherry-picking. A concurrency test runs parallel officers against one queue.
- Officers lose flexibility (a specialist cannot take "their kind" of case). Categories and departments are the tool for that.
- Priority becomes the lever that matters, so changing it is restricted to staff and audited.
