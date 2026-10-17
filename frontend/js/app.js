// CipherQ Main Application Logic (Vanilla ES Module)
import { api } from "./api.js";

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

export async function initApp() {
  const user = await api.getMe();
  
  // Update header/auth badges
  const userBadge = document.getElementById("user-badge");
  const planBadge = document.getElementById("plan-badge");
  const roleSelect = document.getElementById("role-selector");

  if (userBadge) userBadge.textContent = user.name;
  if (planBadge) {
    planBadge.textContent = user.plan_type;
    planBadge.className = user.plan_type === "PREMIUM" ? "badge badge-premium" : "badge badge-free";
  }

  if (roleSelect) {
    roleSelect.value = api.activeUserRole;
    roleSelect.addEventListener("change", (e) => {
      api.setRole(e.target.value);
      window.location.reload();
    });
  }

  // Update storage meter if present
  const storageMeter = document.getElementById("storage-meter-fill");
  const storageText = document.getElementById("storage-text");
  if (storageMeter && storageText) {
    const percent = Math.min(100, Math.round((user.storage_bytes_used / user.storage_quota_bytes) * 100));
    storageMeter.style.width = percent + "%";
    storageText.textContent = `${formatBytes(user.storage_bytes_used)} of ${formatBytes(user.storage_quota_bytes)} used (${percent}%)`;
  }

  // File Manager page logic
  const fileTableBody = document.getElementById("file-list-body");
  if (fileTableBody) {
    await renderFileList(fileTableBody);
    setupDropzone();
  }

  // AI Chat page logic
  const aiForm = document.getElementById("ai-chat-form");
  if (aiForm) {
    setupAIChat(user);
  }
}

async function renderFileList(container) {
  container.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Loading encrypted files...</td></tr>`;
  const files = await api.listFiles();

  if (files.length === 0) {
    container.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding: 2rem;">No encrypted files found in your vault.</td></tr>`;
    return;
  }

  container.innerHTML = files.map(file => `
    <tr id="row-${file.id}">
      <td>
        <strong style="color:var(--text-primary);">${file.original_name}</strong>
        <div style="font-size:0.75rem; color:var(--text-muted); font-family:monospace;">SHA256: ${file.sha256_hash.substring(0, 16)}...</div>
      </td>
      <td>${formatBytes(file.file_size_bytes)}</td>
      <td>
        <span class="badge ${file.is_indexed ? 'badge-success' : 'badge-free'}">
          ${file.is_indexed ? 'Indexed' : 'Encrypted Only'}
        </span>
      </td>
      <td>${new Date(file.created_at).toLocaleDateString()}</td>
      <td style="text-align:right;">
        <button class="btn btn-outline btn-sm download-btn" data-id="${file.id}">Download</button>
        <button class="btn btn-danger btn-sm delete-btn" data-id="${file.id}">Delete</button>
      </td>
    </tr>
  `).join("");

  // Attach event listeners
  container.querySelectorAll(".delete-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const id = e.target.getAttribute("data-id");
      if (confirm("Are you sure you want to delete this file? This will trigger the recoverable cleanup workflow.")) {
        await api.deleteFile(id);
        const row = document.getElementById(`row-${id}`);
        if (row) {
          row.style.opacity = "0.5";
          row.innerHTML = `<td colspan="5" style="color:var(--accent-warning); text-align:center;">Purging from encrypted vault and scrubbing AI index...</td>`;
          setTimeout(() => row.remove(), 800);
        }
      }
    });
  });

  container.querySelectorAll(".download-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const id = e.target.getAttribute("data-id");
      alert(`Streaming decryption triggered for file ${id}. In production, this streams verified plaintext directly to your browser.`);
    });
  });
}

function setupDropzone() {
  const dropzone = document.getElementById("file-dropzone");
  const fileInput = document.getElementById("file-input");

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      await handleUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", async (e) => {
    if (e.target.files.length > 0) {
      await handleUpload(e.target.files[0]);
    }
  });
}

async function handleUpload(file) {
  const dropzone = document.getElementById("file-dropzone");
  const originalHtml = dropzone.innerHTML;
  dropzone.innerHTML = `<div style="color:var(--accent-cyan); font-weight:600;">Streaming & Encrypting ${file.name}...</div>`;

  await api.uploadFile(file);
  dropzone.innerHTML = `<div style="color:var(--accent-success); font-weight:600;">Uploaded & Encrypted with unique DEK!</div>`;
  setTimeout(() => {
    dropzone.innerHTML = originalHtml;
    const body = document.getElementById("file-list-body");
    if (body) renderFileList(body);
  }, 1200);
}

function setupAIChat(user) {
  const form = document.getElementById("ai-chat-form");
  const input = document.getElementById("ai-chat-input");
  const history = document.getElementById("ai-chat-history");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;

    // Append user message
    const userMsg = document.createElement("div");
    userMsg.className = "card";
    userMsg.style.marginBottom = "1rem";
    userMsg.style.borderLeft = "4px solid var(--accent-cyan)";
    userMsg.innerHTML = `<strong style="color:var(--accent-cyan);">You:</strong> <p>${prompt}</p>`;
    history.appendChild(userMsg);
    input.value = "";

    // Loading indicator
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "card";
    loadingMsg.style.marginBottom = "1rem";
    loadingMsg.innerHTML = `<em style="color:var(--text-muted);">Querying local search engine...</em>`;
    history.appendChild(loadingMsg);
    history.scrollTop = history.scrollHeight;

    const result = await api.queryAI(prompt);
    loadingMsg.remove();

    const botMsg = document.createElement("div");
    botMsg.className = "card";
    botMsg.style.marginBottom = "1rem";

    if (result.error) {
      botMsg.style.borderLeft = "4px solid var(--accent-warning)";
      botMsg.innerHTML = `
        <strong style="color:var(--accent-warning);">Plan Restriction Notice:</strong>
        <p style="margin-top:0.5rem;">${result.error}</p>
        <p style="font-size:0.85rem; color:var(--text-muted); margin-top:0.5rem;">
          To test local AI Q&A, switch to the <strong>Alex Vance (PREMIUM)</strong> test profile using the profile switcher in the top navigation.
        </p>
      `;
    } else {
      botMsg.style.borderLeft = "4px solid var(--accent-blue)";
      const sourcesHtml = result.sources.map(s => `
        <span class="badge badge-free" style="margin-right:0.4rem; margin-top:0.4rem;">
          📄 ${s.filename} (Page ${s.page || s.line || 1})
        </span>
      `).join("");

      botMsg.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong style="color:var(--accent-cyan-light);">CipherQ Local AI (${result.mode}):</strong>
          <span class="badge badge-success">Offline / Local</span>
        </div>
        <p style="margin-top:0.75rem;">${result.answer}</p>
        <div style="margin-top:1rem; border-top:1px solid rgba(72,202,228,0.1); padding-top:0.5rem;">
          <small style="color:var(--text-muted); display:block; margin-bottom:0.25rem;">Citations & Sources:</small>
          ${sourcesHtml}
        </div>
      `;
    }
    history.appendChild(botMsg);
    history.scrollTop = history.scrollHeight;
  });
}

document.addEventListener("DOMContentLoaded", initApp);
