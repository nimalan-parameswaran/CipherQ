// CipherQ Frontend API Client (Vanilla ES Module)
import { MOCK_USERS, MOCK_FILES, MOCK_AI_RESPONSES } from "./mock-data.js";

class CipherQAPIClient {
  constructor() {
    this.baseUrl = window.location.origin.includes(":8000") 
      ? "/api/v1" 
      : "http://localhost:8000/api/v1";
    this.useMock = false;
    this.csrfToken = localStorage.getItem("cipherq_csrf") || "mock_csrf_token_xyz";
    this.activeUserRole = localStorage.getItem("cipherq_active_role") || "free";
  }

  setRole(role) {
    this.activeUserRole = role;
    localStorage.setItem("cipherq_active_role", role);
  }

  getCurrentMockUser() {
    return MOCK_USERS[this.activeUserRole] || MOCK_USERS.free;
  }

  async getMe() {
    try {
      const res = await fetch(`${this.baseUrl}/auth/me`, {
        credentials: "include",
        headers: { "X-CSRF-Token": this.csrfToken }
      });
      if (res.ok) return await res.json();
    } catch {
      // Backend not running; fallback to mock user for Phase 1
    }
    return this.getCurrentMockUser();
  }

  async listFiles() {
    try {
      const res = await fetch(`${this.baseUrl}/files`, {
        credentials: "include"
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback to mock files
    }
    const currentUserId = this.getCurrentMockUser().id;
    return MOCK_FILES.filter(f => f.user_id === currentUserId && f.status !== "DELETED");
  }

  async uploadFile(fileObj, onProgress) {
    try {
      const formData = new FormData();
      formData.append("file", fileObj);
      const res = await fetch(`${this.baseUrl}/files`, {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": this.csrfToken },
        body: formData
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback mock upload
    }
    // Simulate upload delay
    if (onProgress) onProgress(100);
    const mockFile = {
      id: "fil_" + Math.random().toString(36).substring(2, 10),
      user_id: this.getCurrentMockUser().id,
      original_name: fileObj.name,
      file_size_bytes: fileObj.size,
      mime_type: fileObj.type || "application/octet-stream",
      sha256_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      is_indexed: false,
      status: "ACTIVE",
      created_at: new Date().toISOString()
    };
    MOCK_FILES.unshift(mockFile);
    return mockFile;
  }

  async deleteFile(fileId) {
    try {
      const res = await fetch(`${this.baseUrl}/files/${fileId}`, {
        method: "DELETE",
        credentials: "include",
        headers: { "X-CSRF-Token": this.csrfToken }
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback mock delete
    }
    const target = MOCK_FILES.find(f => f.id === fileId);
    if (target) {
      target.status = "DELETED";
    }
    return { success: true, file_id: fileId, status: "PENDING_DELETION" };
  }

  async queryAI(prompt) {
    const user = this.getCurrentMockUser();
    if (user.plan_type === "FREE") {
      // Free users only have keyword search
      return {
        error: "AI Document Q&A requires the PREMIUM tier. Free tier is restricted to keyword search.",
        upgrade_required: true
      };
    }

    try {
      const res = await fetch(`${this.baseUrl}/ai/chat`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": this.csrfToken
        },
        body: JSON.stringify({ prompt })
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback mock response
    }
    
    // Return mock cited answer
    const match = MOCK_AI_RESPONSES.find(r => prompt.toLowerCase().includes("memory") || prompt.toLowerCase().includes("linux")) || MOCK_AI_RESPONSES[0];
    return match;
  }
}

export const api = new CipherQAPIClient();
