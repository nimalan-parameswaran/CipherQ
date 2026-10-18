/**
 * CipherQ Frontend Runtime Configuration
 *
 * PURPOSE:
 *   Provides the public backend API base URL for cross-origin (deployed) operation.
 *   When frontend is served from GitHub Pages / Cloudflare Pages and the backend
 *   is reached via Cloudflare Tunnel, this file bridges the two origins securely.
 *
 * HOW TO CONFIGURE FOR PRODUCTION:
 *   Set CIPHERQ_API_BASE_URL to your Cloudflare Tunnel public hostname, e.g.:
 *     window.CIPHERQ_API_BASE_URL = "https://your-tunnel.example.com";
 *   Or use the placeholder below and deploy this file with the correct value.
 *
 * LOCAL DEVELOPMENT:
 *   Leave CIPHERQ_API_BASE_URL as an empty string ("") or omit it entirely.
 *   The API client will fall back to the relative path /api/v1, which works
 *   when the FastAPI dev server serves both frontend and backend on the same origin.
 *
 * SECURITY:
 *   - Do NOT embed secrets, tokens, passwords, or encryption keys here.
 *   - Do NOT commit production tunnel hostnames to a public repository.
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

// Set this to your public Cloudflare Tunnel HTTPS URL in production.
// Example: "https://your-tunnel.trycloudflare.com"
// Leave empty for local development (falls back to same-origin /api/v1).
window.CIPHERQ_API_BASE_URL = "";
