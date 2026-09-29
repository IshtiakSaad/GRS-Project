# 7. Files go straight to object storage and are checked afterwards

**Status:** accepted

## Context

Citizens attach scans and photos over slow mobile connections. If uploads pass through the API, one slow 10 MB upload holds a web worker for minutes. Files also cannot be trusted: the name and declared type say nothing about the content.

## Decision

The API returns a short-lived signed URL; the phone uploads directly to S3-compatible storage (self-hosted SeaweedFS, so files stay in-country). The client then confirms, and a background task checks the size, detects the real type from the first bytes, computes a SHA-256 and passes the content through a scanner interface. Only then is the file downloadable, again by signed URL. Uploads whose check was lost are swept and retried.

## Alternatives considered

- **Upload through the API.** One request, simple client code, and a worker held hostage by every slow phone. On 2G a 5 MB scan takes minutes.
- **Store files in PostgreSQL.** One backup covers everything, and the database grows by gigabytes of images it never queries.
- **A public cloud bucket.** Cheapest and most durable, and citizens' documents would sit with a foreign provider. The storage speaks the S3 API either way, so this stays an operational choice, not a code change.
- **Scan before accepting the upload.** Would keep bad files out of storage entirely, but only by routing the bytes through the API again. Files are stored, quarantined until checked, and never served before.

## Consequences

- Web workers never carry file bytes; Nginx only proxies the storage host.
- A file is unavailable for a few seconds after upload while it is checked.
- Production scans with ClamAV (clamd, signatures updated every 2 hours), streamed from storage so the file is never held in memory. If ClamAV is down the file waits unverified and is retried; it is never approved without a scan. Locally a stand-in flags the EICAR test file, as ClamAV does, so the stack runs without ClamAV's 1.5 GB of memory.
- The storage speaks only the S3 API, so it can be replaced without code changes.

## What would change this

Photos taken on phones carry location and device metadata. Re-encoding images after the scan would strip it; see [scope](../scope.md).
