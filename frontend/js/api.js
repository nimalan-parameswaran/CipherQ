// CipherQ Frontend API Client (Connected to Real FastAPI Endpoints)
// Session tokens are handled strictly via HttpOnly cookies (never stored in client storage).
// Only the CSRF token is held in sessionStorage for header injection on mutating requests.

class CipherQAPIClient {
  constructor() {
    // Single-origin default; falls back to current host /api/v1
    this.baseUrl = "/api/v1";
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
    const res = await fetch(`${this.baseUrl}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, plan_type: planType })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Registration failed." }));
      throw new Error(this._formatError(err, "Registration failed."));
    }
    return await res.json();
  }

  async login(email, password) {
    const res = await fetch(`${this.baseUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
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
      await fetch(`${this.baseUrl}/auth/logout`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrf }
      });
    } finally {
      this.setCSRFToken(null);
    }
  }

  async getMe() {
    try {
      const res = await fetch(`${this.baseUrl}/auth/me`, {
        headers: { "X-CSRF-Token": this.getCSRFToken() }
      });
      if (res.status === 401) {
        this.setCSRFToken(null);
        return null;
      }
      if (!res.ok) {
        return null;
      }
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async getUsage() {
    try {
      const res = await fetch(`${this.baseUrl}/auth/usage`, {
        headers: { "X-CSRF-Token": this.getCSRFToken() }
      });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async listFiles() {
    const res = await fetch(`${this.baseUrl}/files`, {
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    });
    if (res.status === 401) {
      return null;
    }
    if (!res.ok) {
      throw new Error("Failed to list files from vault.");
    }
    return await res.json();
  }

  uploadFile(fileObj, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${this.baseUrl}/files`, true);
      xhr.setRequestHeader("X-CSRF-Token", this.getCSRFToken());

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
    const res = await fetch(`${this.baseUrl}/files/${fileId}/download`);
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
    const res = await fetch(`${this.baseUrl}/files/${fileId}`, {
      method: "DELETE",
      headers: { "X-CSRF-Token": this.getCSRFToken() }
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Deletion failed." }));
      throw new Error(err.detail || "Deletion failed.");
    }
    return await res.json();
  }
}

export const api = new CipherQAPIClient();
