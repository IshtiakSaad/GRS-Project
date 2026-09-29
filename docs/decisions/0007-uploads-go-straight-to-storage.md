# 7. Files go straight to object storage and are checked afterwards

**Status:** accepted

## Context

Citizens attach scans and photos over slow mobile connections. If uploads pass through the API, one slow 10 MB upload holds a web worker for minutes. Files also cannot be trusted: the name and declared type say nothing about the content.

## Decision

The API returns a short-lived signed URL; the phone uploads directly to S3-compatible storage (self-hosted SeaweedFS, so files stay in-country). The client then confirms, and a background task checks the size, detects the real type from the first bytes, computes a SHA-256 and passes the content through a scanner interface. Only then is the file downloadable, again by signed URL. Uploads whose check was lost are swept and retried.

## Consequences

- Web workers never carry file bytes; Nginx only proxies the storage host.
- A file is unavailable for a few seconds after upload while it is checked.
- Production scans with ClamAV (clamd, signatures updated every 2 hours), streamed from storage so the file is never held in memory. If ClamAV is down the file waits unverified and is retried; it is never approved without a scan. Locally a stand-in flags the EICAR test file, as ClamAV does, so the stack runs without ClamAV's 1.5 GB of memory.
- The storage speaks only the S3 API, so it can be replaced without code changes.
