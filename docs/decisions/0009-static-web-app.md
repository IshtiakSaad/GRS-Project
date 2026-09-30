# 9. The web app is static files served by the same Nginx

**Status:** accepted

## Context

Citizens, officers and administrators need screens, not only an API. Most citizens use cheap Android phones on slow mobile data. The system already runs on one server (decision 8), and every extra long-running process is one more thing to size, restart and watch.

## Decision

The web app lives in `web/`: Next.js with TypeScript, built with `output: "export"` into plain HTML, JavaScript and CSS. The Nginx image is built from it (`web/Dockerfile`), so the files ship with each deploy and roll back with it. Nginx serves the app at `/` and keeps `/api/` and `/health/` for Django, on one origin: no CORS on the API, and a strict Content-Security-Policy on the pages.

- Every page renders in the browser and reads the API. Pages that show one record take its id in the query string (`/requests/view/?id=…`), since a static export has no server to resolve a path.
- The access token is kept in memory only. The refresh token is kept in `sessionStorage` on a shared device and in `localStorage` when the user says the device is their own: the same two trust modes the API gives sessions. A refused token triggers one refresh, shared by every call waiting on it.
- Bangla is the default language, English one tap away. The API is asked in the same language, so its error messages need no second translation.
- Files go from the browser to object storage with the signed URL (decision 7); the files host allows only the app's origin to do so.
- Playwright walks one request through all three roles on a phone-sized screen, against the full Compose stack, in CI.

## Alternatives considered

- **Server-rendered Django templates.** The strongest alternative: HTML on first byte, no JavaScript needed, excellent on 2G. We chose a client app because the API is the product, and the web app should be its first client, using exactly the endpoints any other client would. Every screen is a proof that the API is enough.
- **Next.js with a Node server** (server rendering). Faster first paint, and one more long-running process to size, restart and secure beside Django.
- **A native Android app.** The best experience on the phones most citizens have, and an install, an app store and an update cycle between a citizen and their first request.

## Consequences

- No Node process in production; the app costs a few megabytes of disk and nothing at run time.
- A first visit downloads the JavaScript before anything shows. Pages are small and cached (`/_next/static/` is immutable), but there is no server-rendered first paint, and drafts need a connection ([scope](../scope.md)).
- A refresh token in browser storage can be read by script running on the page. The CSP allows only this origin's scripts; the token rotates, and reuse of an old one ends every session of the account.
- The CSP needs `'unsafe-inline'` for scripts because the export inlines its bootstrap. Nonces would need a server.

## What would change this

Measured first-load times on 2G that stop citizens finishing a request. The answer would be server-rendered pages for the citizen's few most-used screens, not a rewrite.
