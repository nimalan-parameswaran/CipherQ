# GitHub Pages frontend deployment

This document covers the static frontend only. The existing FastAPI service,
database, encrypted vault, local Gemma inference, and Arduino UNO Q environment
are not changed by the Pages deployment.

## Site and deployment settings

For this repository, the project-site URL is:

`https://nimalan-parameswaran.github.io/CipherQ/`

The workflow in `.github/workflows/pages.yml` stages only `frontend/`. It does
not publish `backend/`, `data/`, `keys/`, `.env` files, databases, models,
virtual environments, logs, or other repository files.

After reviewing the local changes, manually enable Pages:

1. Open **Settings → Pages** in `nimal-parameswaran/CipherQ`.
2. Set **Source** to **GitHub Actions**.
3. Do not use a branch/folder source alongside this workflow.
4. Push the reviewed commit to `main`, or run the workflow from the
   **Actions** tab with **Run workflow**.

Do not enable settings or push changes automatically as part of this task.

## API configuration

`frontend/js/config.js` is the single public configuration point used by every
page. For local development, leave this value empty so requests use the
same-origin `/api/v1` path:

```js
window.CIPHERQ_API_BASE_URL = "";
```

After a secure public API endpoint exists, set it to its HTTPS origin, without
the `/api/v1` suffix, then deploy the frontend:

```js
window.CIPHERQ_API_BASE_URL = "https://api.example.com";
```

The client appends `/api/v1` and preserves the existing request paths, request
bodies, HttpOnly-cookie session design, CSRF header handling, and
`credentials: "include"` behavior. The URL is not a secret. Never put
passwords, tokens, private keys, master keys, local IP addresses, or local
development URLs in it.

If the URL is empty on GitHub Pages, or the backend cannot be reached, the UI
shows a backend-unavailable message and does not use mock data or claim that a
request succeeded.

## Remote backend architecture

GitHub Pages cannot reach a private LAN address. The intended later architecture
is:

```text
User browser
  → GitHub Pages frontend
  → HTTPS public backend endpoint
  → restricted secure tunnel
  → Arduino UNO Q FastAPI backend
  → existing local Gemma AI and encrypted storage
```

Cloudflare Tunnel is a suitable option for the later phase. Configure it on the
Arduino only after an explicit infrastructure change review; this task does
not install, configure, connect to, restart, or test a tunnel. Use a named
tunnel and route only the approved application hostname to the existing
FastAPI listener. Do not forward the Gemma port, SSH, an administrative
interface, or arbitrary LAN destinations. Apply tunnel-side access controls
and origin restrictions appropriate to the chosen deployment.

Until the public HTTPS endpoint and tunnel are configured and tested from
outside the local network, the website is only a deployed static frontend.
Login, registration, vault operations, indexing, AI queries, account data, and
plan operations remain unavailable remotely.

## CORS and cookie change requiring approval

Inspection found no CORS middleware in the current backend. Do not apply this
change automatically. The minimal proposed backend change is:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nimalan-parameswaran.github.io"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Admin-Token"],
    expose_headers=["Content-Disposition"],
)
```

CORS compares origins, not the `/CipherQ/` path. The backend must also use
`COOKIE_SECURE=True` and a cross-site-compatible cookie policy such as
`COOKIE_SAMESITE=none` when the browser and API are on different sites. These
backend changes require a separate approval and controlled deployment on the
Arduino; they are not part of this frontend change.

## Production security checklist

Before exposing the API publicly, verify:

- HTTPS is enforced for the public endpoint and backend cookie security is
  enabled.
- Every protected route enforces authentication and authorization, including
  file ownership, indexing, AI, account, and plan operations.
- Session cookies remain HttpOnly, Secure, appropriately SameSite-scoped, and
  are revoked on logout/expiry.
- Cookie-based mutations use CSRF protection and the CORS policy is explicit;
  never use wildcard origins with credentials.
- Upload size, content type, streaming, quota, and disk-headroom limits are
  enforced at both proxy and application boundaries.
- Authentication and expensive AI routes have rate limiting and monitoring.
- The master key, admin token, database, encrypted files, and logs remain
  private and are never included in the Pages artifact.
- Public errors do not reveal secrets, filesystem paths, SQL details, or
  document contents; logs are access-controlled and do not record credentials.
- Administrative functions are not exposed through an unrestricted public
  interface and require separate authorization.
- Users cannot enumerate, download, index, delete, or retrieve another user's
  private files.
