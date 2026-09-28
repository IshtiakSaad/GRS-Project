# 7. Files go straight to object storage and are checked afterwards

**Status:** accepted

## Context

Citizens attach scans and photos over slow mobile connections. If uploads pass through the API, one slow 10 MB upload holds a web worker for minutes. Files also cannot be trusted: the name and declared type say nothing about the content.

## Decision

The API returns a short-lived signed URL; the phone uploads directly to S3-compatible storage (self-hosted SeaweedFS, so files stay in-country). The client then confirms, and a background task checks the size, detects the real type from the first bytes, computes a SHA-256 and passes the content through a scanner interface. Only then is the file downloadable, again by signed URL. Uploads whose check was lost are swept and retried.

## Consequences

- Web workers never carry file bytes; Nginx only proxies the storage host.
- A file is unavailable for a few seconds after upload while it is checked.
- The demo scanner only detects the EICAR test file. ClamAV fits behind the same interface (roadmap).
- The storage speaks only the S3 API, so it can be replaced without code changes.
