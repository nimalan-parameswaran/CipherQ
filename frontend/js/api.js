// CipherQ Frontend API Client (Connected to Real FastAPI Endpoints)
// Session tokens are handled strictly via HttpOnly cookies (never stored in client storage).
// Only the CSRF token is held in sessionStorage for header injection on mutating requests.
//
// CROSS-ORIGIN DEPLOYMENT:
//   When frontend is on a different origin from the backend (e.g. GitHub Pages +
//   Cloudflare Tunnel), set window.CIPHERQ_API_BASE_URL in frontend/js/config.js
//   to the public backend HTTPS URL. All fetch calls automatically include
//   credentials: 'include' when a cross-origin base URL is detected, which is
//   required for the HttpOnly session cookie to be sent across origins.
//   The backend MUST also allow this origin via CORS with allow_credentials=True.
//
// LOCAL DEVELOPMENT:
//   Leave window.CIPHERQ_API_BASE_URL empty (or unset). All requests use the
//   relative path /api/v1 — the same origin as FastAPI. No CORS config needed.

class CipherQAPIClient {
  constructor() {
    // Determine base URL:
    //   1. If window.CIPHERQ_API_BASE_URL is set (non-empty string), use it.
    //      This is the cross-origin production mode (GitHub Pages + Cloudflare Tunnel).
    //   2. Otherwise, fall back to the same-origin relative path /api/v1.
    //      This is local development mode (FastAPI serves both frontend and API).
    const configured = (typeof window !== "undefined" && window.CIPHERQ_API_BASE_URL) || "";

    if (configured) {
      // Strip trailing slash for consistency
      this.baseUrl = configured.replace(/\/$/, "") + "/api/v1";
      this._crossOrigin = true;
    } else {
      this.baseUrl = "/api/v1";
      this._crossOrigin = false;
    }

    // Warn loudly if we're on a non-localhost origin without a configured API URL.
    // This prevents silent failure where a deployed frontend hits /api/v1 on the
    // static host (e.g. GitHub Pages), which has no backend and returns 404.
    if (
      typeof window !== "undefined" &&
      !configured &&
      window.location.hostname !== "localhost" &&
      window.location.hostname !== "127.0.0.1"
    ) {
      console.error(
        "[CipherQ] CONFIGURATION ERROR: The frontend appears to be deployed to a " +
        "non-localhost origin (" + window.location.hostname + ") but " +
        "window.CIPHERQ_API_BASE_URL is not set in frontend/js/config.js. " +
        "API requests will fail. Set CIPHERQ_API_BASE_URL to your Cloudflare Tunnel URL."
      );
    }
  }

  // Returns fetch options that include credentials when cross-origin.
  // credentials: 'include' is required for the HttpOnly session cookie to be
  // sent to a different origin. On same-origin requests, 'same-origin' is
  // sufficient and avoids unnecessary preflight on simple requests.
  _fetchOptions(extra = {}) {
    return {
      credentials: this._crossOrigin ? "include" : "same-origin",
      ...extra,
    };
  }

  getCSRFToken() {
    return sessionStorage.getItem("cipherq_csrf") || "";
  }

  setCSRFToken(token) {
    if (token) {
      sessionStorage.setItem("cipherq_csrf", token);
    } else {
      sessionStorage.removeItem("cipherq_csrf");
    }
  }

  _formatError(err, fallback) {
    if (!err) return fallback;
    if (typeof err.detail === "string") return err.detail;
    if (Array.isArray(err.detail)) {
      return err.detail.map(d => d.msg || d.loc?.join(".") || "Invalid input").join("; ");
    }
    return err.message || fallback;
  }

  async register(email, password, planType = "FREE") {
    const res = await fetch(`${this.baseUrl}/auth/register`, this._fetchOptions({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, plan_type: planType })
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Registration failed." }));
      throw new Error(this._formatError(err, "Registration failed."));
    }
    return await res.json();
  }

  async login(email, password) {
    const res = await fetch(`${this.baseUrl}/auth/login`, this._fetchOptions({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Invalid email or password." }));
      throw new Error(this._formatError(err, "Invalid email or password."));
    }
    const data = await res.json();
    this.setCSRFToken(data.csrf_token);
    return data;
  }

  async logout() {
    const csrf = this.getCSRFToken();
    try {
      await fetch(`${this.baseUrl}/auth/logout`, this._fetchOptions({
        method: "POST",
        headers: { "X-CSRF-Token": csrf }
      }));
    } finally {
      this.setCSRFToken(null);
    }
  }

  async getMe() {
    try {
      const res = await fetch(`${this.baseUrl}/auth/me`, this._fetchOptions({
        headers: { "X-CSRF-Token": this.getCSRFToken() }
      }));
      if (res.status === 401) {
        this.setCSRFToken(null);
        return null;
      }
      if (!res.ok) {
        return null;
      }
      const data = await res.json();
      if (data && data.csrf_token) {
        this.setCSRFToken(data.csrf_token);
      }
      return data;
    } catch (e) {
      return null;
    }
  }

  async getUsage() {
    try {
      const res = await fetch(`${this.baseUrl}/auth/usage`, this._fetchOptions({
        headers: { "X-CSRF-Token": this.getCSRFToken() }
      }));
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async listFiles() {
    const res = await fetch(`${this.baseUrl}/files`, this._fetchOptions({
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    }));
    if (res.status === 401) {
      return null;
    }
    if (!res.ok) {
      throw new Error("Failed to list files from vault.");
    }
    const data = await res.json();
    return Array.isArray(data) ? data : (data.files || []);
  }

  uploadFile(fileObj, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${this.baseUrl}/files`, true);
      xhr.setRequestHeader("X-CSRF-Token", this.getCSRFToken());

      // Send cookies cross-origin when configured for production deployment.
      // withCredentials is the XHR equivalent of fetch's credentials: 'include'.
      xhr.withCredentials = this._crossOrigin;

      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            onProgress(percent);
          }
        };
      }

      xhr.onload = () => {
        if (xhr.status === 201) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (e) {
            resolve({ success: true });
          }
        } else {
          try {
            const err = JSON.parse(xhr.responseText);
            reject(new Error(err.detail || `Upload failed (HTTP ${xhr.status})`));
          } catch {
            reject(new Error(`Upload failed with HTTP ${xhr.status}`));
          }
        }
      };

      xhr.onerror = () => reject(new Error("Network connection error during streaming upload."));
      xhr.onabort = () => reject(new Error("Upload aborted."));

      const formData = new FormData();
      formData.append("file", fileObj);
      xhr.send(formData);
    });
  }

  async downloadFile(fileId, filename) {
    const res = await fetch(`${this.baseUrl}/files/${fileId}/download`, this._fetchOptions());
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Download failed." }));
      throw new Error(err.detail || "Download failed.");
    }

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.style.display = "none";
    a.href = url;
    a.download = filename || "downloaded_file";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      window.URL.revokeObjectURL(url);
      a.remove();
    }, 1000);
  }

  async deleteFile(fileId) {
    const res = await fetch(`${this.baseUrl}/files/${fileId}`, this._fetchOptions({
      method: "DELETE",
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Deletion failed." }));
      throw new Error(err.detail || "Deletion failed.");
    }
    return await res.json();
  }

  async indexFile(fileId) {
    const res = await fetch(`${this.baseUrl}/ai/index/${fileId}`, this._fetchOptions({
      method: "POST",
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Indexing failed." }));
      throw new Error(err.detail || "Indexing failed.");
    }
    return await res.json();
  }

  async unindexFile(fileId) {
    const res = await fetch(`${this.baseUrl}/ai/index/${fileId}`, this._fetchOptions({
      method: "DELETE",
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unindexing failed." }));
      throw new Error(err.detail || "Unindexing failed.");
    }
    return await res.json();
  }

  async queryAI(query, limit = 5) {
    const res = await fetch(`${this.baseUrl}/ai/query`, this._fetchOptions({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.getCSRFToken()
      },
      body: JSON.stringify({ query, limit })
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "AI Query failed." }));
      throw new Error(err.detail || "AI Query failed.");
    }
    return await res.json();
  }

  async adminChangePlan(email, newPlan, adminToken, reason = "dev_admin_ui") {
    const res = await fetch(`${this.baseUrl}/admin/users/plan`, this._fetchOptions({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": adminToken
      },
      body: JSON.stringify({ email, new_plan: newPlan, reason })
    }));
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Plan modification failed." }));
      throw new Error(err.detail || "Plan modification failed.");
    }
    return await res.json();
  }
}

export const api = new CipherQAPIClient();
