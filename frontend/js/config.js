/**
 * CipherQ Frontend Runtime Configuration
 *
 * PURPOSE:
 *   Provides the public backend API base URL for cross-origin (deployed) operation.
 *   When frontend is served from GitHub Pages / Cloudflare Pages and the backend
 *   is reached via Cloudflare Tunnel, this file bridges the two origins securely.
 *
 * HOW TO CONFIGURE FOR PRODUCTION:
 *   Set CIPHERQ_API_BASE_URL to the HTTPS hostname of the approved public API
 *   endpoint, for example:
 *     window.CIPHERQ_API_BASE_URL = "https://api.example.com";
 *   This value is public configuration, not a secret. Do not put credentials,
 *   tokens, private keys, or local-network addresses here.
 *
 * LOCAL DEVELOPMENT:
 *   Leave CIPHERQ_API_BASE_URL as an empty string (""). The API client will use
 *   the relative path /api/v1 when FastAPI serves the frontend and API together.
 *
 * SECURITY:
 *   - Do NOT embed secrets, tokens, passwords, or encryption keys here.
 *   - This file is intentionally NOT a secret; it contains only a public URL.
 *
 * IMPORTANT - SameSite cookie behaviour:
 *   When the frontend origin (e.g. your-name.github.io) differs from the
 *   backend origin (e.g. your-tunnel.trycloudflare.com), the session cookie
 *   is cross-site. The backend MUST set:
 *     SameSite=None; Secure
 *   AND all fetch() calls MUST include credentials: 'include'.
 *   Both are handled automatically when CIPHERQ_API_BASE_URL is non-empty.
 */

// Set this to the approved public HTTPS API origin before a production deploy.
// Leave empty for local development (same-origin /api/v1).
window.CIPHERQ_API_BASE_URL = "https://disclaimers-targets-studied-scheduled.trycloudflare.com";
