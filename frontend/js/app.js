// CipherQ Main Application Logic (Vanilla ES Module)
// Seamlessly integrated with FastAPI backend authentication, streaming vault I/O, and usage metering.
import { api } from "./api.js";

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  if (bytes === 1000000000) return "1 GB";
  if (bytes === 5000000000) return "5 GB";
  const k = 1000; // Decimal GB standard
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

// ---------------------------------------------------------
// Auth Modal & State Management
// ---------------------------------------------------------
function ensureAuthModal() {
  if (document.getElementById("auth-modal")) return;

  const modalHtml = `
    <div id="auth-modal" class="modal-backdrop" style="display:none;">
      <div class="modal-card">
        <div class="modal-header">
          <div class="modal-title" id="auth-modal-title">Sign In to CipherQ</div>
          <button class="modal-close" id="auth-modal-close" aria-label="Close">&times;</button>
        </div>
        <div class="modal-tabs">
          <button type="button" class="modal-tab-btn active" id="tab-login">Log In</button>
          <button type="button" class="modal-tab-btn" id="tab-register">Create Account</button>
        </div>
        <div class="modal-body">
          <div id="auth-alert" class="alert alert-danger" style="display:none;"></div>

          <!-- Login Form -->
          <form id="form-login">
            <div class="form-group">
              <label class="form-label" for="login-email">Email Address</label>
              <input type="email" id="login-email" class="form-control" required placeholder="you@example.com" autocomplete="username">
            </div>
            <div class="form-group">
              <label class="form-label" for="login-password">Password</label>
              <input type="password" id="login-password" class="form-control" required placeholder="••••••••••••" autocomplete="current-password">
            </div>
            <button type="submit" id="btn-submit-login" class="btn btn-primary" style="width:100%; margin-top:0.5rem;">
              Log In to Vault
            </button>
          </form>

          <!-- Register Form -->
          <form id="form-register" style="display:none;">
            <div class="form-group">
              <label class="form-label" for="reg-email">Email Address</label>
              <input type="email" id="reg-email" class="form-control" required placeholder="you@example.com" autocomplete="username">
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-password">Password</label>
              <input type="password" id="reg-password" class="form-control" required placeholder="At least 8 characters" autocomplete="new-password">
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-plan">Select Plan Tier</label>
              <select id="reg-plan" class="form-control">
                <option value="FREE">FREE Plan (1 GB Quota, Streaming AEAD)</option>
                <option value="PREMIUM">PREMIUM Plan (5 GB Quota + Local AI Search)</option>
              </select>
            </div>
            <button type="submit" id="btn-submit-register" class="btn btn-primary" style="width:100%; margin-top:0.5rem;">
              Register & Initialize Vault
            </button>
          </form>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML("beforeend", modalHtml);

  // Tab switching
  const tabLogin = document.getElementById("tab-login");
  const tabRegister = document.getElementById("tab-register");
  const formLogin = document.getElementById("form-login");
  const formRegister = document.getElementById("form-register");
  const modalTitle = document.getElementById("auth-modal-title");
  const authAlert = document.getElementById("auth-alert");

  tabLogin.addEventListener("click", () => {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    formLogin.style.display = "block";
    formRegister.style.display = "none";
    modalTitle.textContent = "Sign In to CipherQ";
    authAlert.style.display = "none";
  });

  tabRegister.addEventListener("click", () => {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    formLogin.style.display = "none";
    formRegister.style.display = "block";
    modalTitle.textContent = "Create Your Account";
    authAlert.style.display = "none";
  });

  // Modal close handlers
  document.getElementById("auth-modal-close").addEventListener("click", () => {
    document.getElementById("auth-modal").style.display = "none";
  });

  document.getElementById("auth-modal").addEventListener("click", (e) => {
    if (e.target.id === "auth-modal") {
      document.getElementById("auth-modal").style.display = "none";
    }
  });

  // Form submit handlers
  formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;
    const submitBtn = document.getElementById("btn-submit-login");

    try {
      submitBtn.disabled = true;
      submitBtn.textContent = "Authenticating...";
      authAlert.style.display = "none";

      await api.login(email, password);
      document.getElementById("auth-modal").style.display = "none";
      window.location.reload();
    } catch (err) {
      authAlert.textContent = err.message || "Login failed.";
      authAlert.style.display = "flex";
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Log In to Vault";
    }
  });

  formRegister.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("reg-email").value.trim();
    const password = document.getElementById("reg-password").value;
    const plan = document.getElementById("reg-plan").value;
    const submitBtn = document.getElementById("btn-submit-register");

    try {
      submitBtn.disabled = true;
      submitBtn.textContent = "Creating account...";
      authAlert.style.display = "none";

      await api.register(email, password, plan);
      // Automatically log in after registration
      await api.login(email, password);
      document.getElementById("auth-modal").style.display = "none";
      window.location.reload();
    } catch (err) {
      authAlert.textContent = err.message || "Registration failed.";
      authAlert.style.display = "flex";
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Register & Initialize Vault";
    }
  });
}

export function openAuthModal(mode = "login") {
  ensureAuthModal();
  const modal = document.getElementById("auth-modal");
  const tabLogin = document.getElementById("tab-login");
  const tabRegister = document.getElementById("tab-register");
  if (mode === "register") {
    tabRegister.click();
  } else {
    tabLogin.click();
  }
  modal.style.display = "flex";
}

// ---------------------------------------------------------
// Navigation & User Display
// ---------------------------------------------------------
function updateNavbar(user) {
  const navActions = document.querySelector(".nav-actions");
  if (!navActions) return;

  if (user) {
    navActions.innerHTML = `
      <span id="user-display" style="font-size:0.85rem; color:var(--text-primary); font-weight:600; padding:0.35rem 0.5rem;">
        ${user.email}
      </span>
      <span id="plan-badge" class="badge ${user.plan_type === 'PREMIUM' ? 'badge-premium' : 'badge-free'}">
        ${user.plan_type}
      </span>
      <button id="btn-nav-logout" class="btn btn-outline btn-sm">Log Out</button>
    `;
    document.getElementById("btn-nav-logout").addEventListener("click", async () => {
      await api.logout();
      window.location.href = "index.html";
    });
  } else {
    navActions.innerHTML = `
      <button id="btn-nav-login" class="btn btn-outline btn-sm">Log In</button>
      <button id="btn-nav-register" class="btn btn-primary btn-sm">Sign Up</button>
    `;
    document.getElementById("btn-nav-login").addEventListener("click", () => openAuthModal("login"));
    document.getElementById("btn-nav-register").addEventListener("click", () => openAuthModal("register"));
  }
}

// ---------------------------------------------------------
// App Initialization
// ---------------------------------------------------------
export async function initApp() {
  ensureAuthModal();
  const user = await api.getMe();
  updateNavbar(user);

  const currentPage = window.location.pathname.split("/").pop() || "index.html";

  // Dashboard Page
  if (document.getElementById("storage-meter-fill") || currentPage.includes("dashboard")) {
    await initDashboard(user);
  }

  // Files Page
  if (document.getElementById("file-list-body") || currentPage.includes("files")) {
    await initFiles(user);
  }

  // AI Chat Page
  if (document.getElementById("ai-chat-form") || currentPage.includes("ai-chat")) {
    await initAIChat(user);
  }

  // Pricing Page
  if (document.getElementById("plan-switcher-body") || currentPage.includes("pricing")) {
    await initPricing(user);
  }
}

// ---------------------------------------------------------
// Pricing & Plan Management Controller
// ---------------------------------------------------------
async function initPricing(user) {
  const container = document.getElementById("plan-switcher-body");
  if (!container) return;

  if (!user) {
    container.innerHTML = `
      <div style="background:rgba(28,37,65,0.4); border:1px solid var(--border-color); border-radius:6px; padding:1rem; text-align:center;">
        <p style="color:var(--text-secondary); margin-bottom:0.75rem;">You must be signed in to manage or switch your subscription tier.</p>
        <button id="pricing-login-btn" class="btn btn-primary btn-sm">Log In to Manage Plan</button>
      </div>
    `;
    const btn = document.getElementById("pricing-login-btn");
    if (btn) btn.addEventListener("click", () => openAuthModal("login"));
    return;
  }

  const isPremium = (user.plan_type === "PREMIUM");
  const targetPlan = isPremium ? "FREE" : "PREMIUM";

  container.innerHTML = `
    <div style="background:rgba(28,37,65,0.6); border:1px solid var(--border-color); border-radius:6px; padding:1.25rem;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem; margin-bottom:1rem;">
        <div>
          <div style="font-size:0.85rem; color:var(--text-muted);">Current Active Account:</div>
          <div style="font-weight:700; font-size:1.1rem; color:var(--text-primary);">${user.email}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.85rem; color:var(--text-muted);">Subscription Plan:</div>
          <span class="badge ${isPremium ? 'badge-premium' : 'badge-free'}" style="font-size:0.9rem;">${user.plan_type}</span>
        </div>
      </div>
      <div id="plan-change-alert" style="display:none; margin-bottom:1rem;"></div>
      <div style="display:flex; gap:1rem; align-items:center; flex-wrap:wrap;">
        <button id="btn-toggle-plan" class="btn ${isPremium ? 'btn-outline' : 'btn-primary'} btn-sm">
          ${isPremium ? 'Downgrade to FREE Plan (1 GB)' : 'Upgrade to PREMIUM Plan (5 GB)'}
        </button>
        <span style="font-size:0.8rem; color:var(--text-muted);">Requires development admin token authentication.</span>
      </div>
    </div>
  `;

  const toggleBtn = document.getElementById("btn-toggle-plan");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", async () => {
      const adminToken = prompt(`Enter Administrative Token to change ${user.email} to ${targetPlan}:`);
      if (!adminToken) return;

      const alertBox = document.getElementById("plan-change-alert");
      try {
        await api.adminChangePlan(user.email, targetPlan, adminToken, "pricing_page_admin_switch");
        alertBox.className = "alert alert-success";
        alertBox.style.display = "block";
        alertBox.textContent = `Successfully updated subscription to ${targetPlan}! Reloading...`;
        setTimeout(() => window.location.reload(), 1000);
      } catch (err) {
        alertBox.className = "alert alert-danger";
        alertBox.style.display = "block";
        alertBox.textContent = `Plan change rejected: ${err.message}`;
      }
    });
  }
}

// ---------------------------------------------------------
// Dashboard View Controller
// ---------------------------------------------------------
async function initDashboard(user) {
  if (!user) {
    const mainContainer = document.querySelector("main.container");
    if (mainContainer) {
      mainContainer.innerHTML = `
        <div class="card auth-lock-card">
          <div style="font-size:3rem; margin-bottom:1rem;">🔐</div>
          <h2 style="font-size:1.5rem; font-weight:800; margin-bottom:0.5rem;">Encrypted Vault Locked</h2>
          <p style="color:var(--text-secondary); margin-bottom:1.5rem;">
            Please log in or create an account to view your dashboard, storage quota, and files.
          </p>
          <div style="display:flex; justify-content:center; gap:1rem;">
            <button id="lock-btn-login" class="btn btn-primary">Log In</button>
            <button id="lock-btn-register" class="btn btn-outline">Sign Up</button>
          </div>
        </div>
      `;
      document.getElementById("lock-btn-login").addEventListener("click", () => openAuthModal("login"));
      document.getElementById("lock-btn-register").addEventListener("click", () => openAuthModal("register"));
    }
    return;
  }

  // Update greeting
  const userBadge = document.getElementById("user-badge");
  if (userBadge) userBadge.textContent = user.email;

  // Update real usage from backend
  const usage = await api.getUsage();
  if (usage) {
    const storageMeter = document.getElementById("storage-meter-fill");
    const storageText = document.getElementById("storage-text");
    if (storageMeter && storageText) {
      const used = usage.storage_bytes_used || 0;
      const quota = usage.storage_quota_bytes || 1073741824;
      const percent = Math.min(100, Math.round((used / quota) * 100));
      storageMeter.style.width = percent + "%";
      storageText.textContent = `${formatBytes(used)} of ${formatBytes(quota)} used (${percent}%)`;
    }

    const aiStatusText = document.getElementById("ai-status-text");
    if (aiStatusText) {
      if (usage.plan_type === "PREMIUM") {
        aiStatusText.textContent = "Semantic Vector Search & Citations (Active)";
        aiStatusText.style.color = "var(--accent-cyan)";
      } else {
        aiStatusText.textContent = "SQLite FTS5 Keyword Search (Included)";
      }
    }
  }
}

// ---------------------------------------------------------
// File Vault View Controller
// ---------------------------------------------------------
async function initFiles(user) {
  if (!user) {
    const mainContainer = document.querySelector("main.container");
    if (mainContainer) {
      mainContainer.innerHTML = `
        <div class="card auth-lock-card">
          <div style="font-size:3rem; margin-bottom:1rem;">📁</div>
          <h2 style="font-size:1.5rem; font-weight:800; margin-bottom:0.5rem;">Vault Access Restricted</h2>
          <p style="color:var(--text-secondary); margin-bottom:1.5rem;">
            You must be logged in to view, upload, download, or delete encrypted vault files.
          </p>
          <div style="display:flex; justify-content:center; gap:1rem;">
            <button id="lock-btn-login" class="btn btn-primary">Log In</button>
            <button id="lock-btn-register" class="btn btn-outline">Sign Up</button>
          </div>
        </div>
      `;
      document.getElementById("lock-btn-login").addEventListener("click", () => openAuthModal("login"));
      document.getElementById("lock-btn-register").addEventListener("click", () => openAuthModal("register"));
    }
    return;
  }

  const fileTableBody = document.getElementById("file-list-body");
  if (fileTableBody) {
    setupDropzone();
    await renderFileList(fileTableBody);
  }
}

async function renderFileList(container) {
  container.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:1.5rem;">Fetching encrypted files from vault...</td></tr>`;
  
  let files;
  try {
    files = await api.listFiles();
  } catch (err) {
    container.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--accent-danger); padding:1.5rem;">Error loading files: ${err.message}</td></tr>`;
    return;
  }

  if (!files || files.length === 0) {
    container.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding: 2.5rem;">No encrypted files found in your vault. Upload a file above to begin.</td></tr>`;
    return;
  }

  container.innerHTML = files.map(file => `
    <tr id="row-${file.id}">
      <td>
        <strong style="color:var(--text-primary); font-size:0.95rem;">${file.original_name}</strong>
        <div style="font-size:0.75rem; color:var(--text-muted); font-family:monospace; margin-top:0.2rem;">
          SHA256: ${file.sha256_hash ? file.sha256_hash.substring(0, 16) + '...' : 'Verified AEAD'}
        </div>
      </td>
      <td>${formatBytes(file.file_size_bytes)}</td>
      <td>
        <span class="badge ${file.is_indexed ? 'badge-success' : 'badge-free'}" id="badge-${file.id}">
          ${file.is_indexed ? 'Encrypted Vault (AI Indexed)' : 'Encrypted Vault'}
        </span>
      </td>
      <td>${new Date(file.created_at).toLocaleDateString()}</td>
      <td style="text-align:right;">
        ${file.is_indexed
          ? `<button class="btn btn-outline btn-sm unindex-btn" data-id="${file.id}">Unindex</button>`
          : `<button class="btn btn-primary btn-sm index-btn" data-id="${file.id}">⚡ Index for AI</button>`
        }
        <button class="btn btn-outline btn-sm download-btn" data-id="${file.id}" data-name="${file.original_name}">
          Download
        </button>
        <button class="btn btn-danger btn-sm delete-btn" data-id="${file.id}">
          Delete
        </button>
      </td>
    </tr>
  `).join("");

  // Attach on-demand index handlers
  container.querySelectorAll(".index-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const targetBtn = e.currentTarget;
      const id = targetBtn.getAttribute("data-id");
      try {
        targetBtn.disabled = true;
        targetBtn.textContent = "Indexing in RAM...";
        await api.indexFile(id);
        await renderFileList(container);
      } catch (err) {
        alert("Indexing failed: " + err.message);
        targetBtn.disabled = false;
        targetBtn.textContent = "⚡ Index for AI";
      }
    });
  });

  // Attach unindex handlers
  container.querySelectorAll(".unindex-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const targetBtn = e.currentTarget;
      const id = targetBtn.getAttribute("data-id");
      try {
        targetBtn.disabled = true;
        targetBtn.textContent = "Removing...";
        await api.unindexFile(id);
        await renderFileList(container);
      } catch (err) {
        alert("Unindexing failed: " + err.message);
        targetBtn.disabled = false;
        targetBtn.textContent = "Unindex";
      }
    });
  });

  // Attach download handlers
  container.querySelectorAll(".download-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const targetBtn = e.currentTarget;
      const id = targetBtn.getAttribute("data-id");
      const name = targetBtn.getAttribute("data-name");
      const originalText = targetBtn.textContent;
      try {
        targetBtn.disabled = true;
        targetBtn.textContent = "Decrypting...";
        await api.downloadFile(id, name);
      } catch (err) {
        alert("Download failed: " + err.message);
      } finally {
        if (targetBtn) {
          targetBtn.disabled = false;
          targetBtn.textContent = originalText;
        }
      }
    });
  });

  // Attach delete handlers
  container.querySelectorAll(".delete-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const id = e.currentTarget.getAttribute("data-id");
      if (!confirm("Are you sure you want to delete this file? This will trigger the recoverable cleanup workflow.")) {
        return;
      }
      try {
        const row = document.getElementById(`row-${id}`);
        if (row) {
          row.style.opacity = "0.5";
          row.innerHTML = `<td colspan="5" style="color:var(--accent-warning); text-align:center; padding:1rem;">Purging from encrypted vault and scrubbing AI index...</td>`;
        }
        await api.deleteFile(id);
        setTimeout(() => {
          if (row) row.remove();
          // Re-render to show empty state if last file
          const remainingRows = container.querySelectorAll("tr");
          if (remainingRows.length === 0) {
            renderFileList(container);
          }
        }, 600);
      } catch (err) {
        alert("Deletion failed: " + err.message);
        renderFileList(container);
      }
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
      fileInput.value = "";
    }
  });
}

async function handleUpload(file) {
  const dropzone = document.getElementById("file-dropzone");
  const originalHtml = dropzone.innerHTML;

  try {
    dropzone.innerHTML = `
      <div style="font-size:2rem; margin-bottom:0.5rem;">⏳</div>
      <div style="color:var(--accent-cyan); font-weight:600; margin-bottom:0.5rem;" id="upload-status-text">
        Streaming & Encrypting ${file.name} (0%)...
      </div>
      <div class="progress-bar-container" style="max-width:300px; margin:0 auto;">
        <div id="upload-progress-fill" class="progress-bar-fill" style="width:0%;"></div>
      </div>
    `;

    const statusText = document.getElementById("upload-status-text");
    const progressFill = document.getElementById("upload-progress-fill");

    await api.uploadFile(file, (percent) => {
      if (statusText) statusText.textContent = `Streaming & Encrypting ${file.name} (${percent}%)...`;
      if (progressFill) progressFill.style.width = `${percent}%`;
    });

    dropzone.innerHTML = `
      <div style="font-size:2rem; margin-bottom:0.5rem; color:var(--accent-success);">✅</div>
      <div style="color:var(--accent-success); font-weight:600;">
        Successfully encrypted and committed to vault!
      </div>
    `;

    setTimeout(() => {
      dropzone.innerHTML = originalHtml;
      const body = document.getElementById("file-list-body");
      if (body) renderFileList(body);
    }, 1200);

  } catch (err) {
    dropzone.innerHTML = `
      <div style="font-size:2rem; margin-bottom:0.5rem; color:var(--accent-danger);">⚠️</div>
      <div style="color:var(--accent-danger); font-weight:700; margin-bottom:0.5rem;">
        Upload Failed
      </div>
      <p style="color:var(--text-primary); font-size:0.9rem; margin-bottom:1rem;">
        ${err.message || "An error occurred during file upload."}
      </p>
      <button class="btn btn-outline btn-sm" id="btn-reset-dropzone">Dismiss</button>
    `;
    document.getElementById("btn-reset-dropzone").addEventListener("click", (e) => {
      e.stopPropagation();
      dropzone.innerHTML = originalHtml;
    });
  }
}

// ---------------------------------------------------------
// AI Chat View Controller
// ---------------------------------------------------------
async function initAIChat(user) {
  if (!user) {
    const mainContainer = document.querySelector("main.container");
    if (mainContainer) {
      mainContainer.innerHTML = `
        <div class="card auth-lock-card">
          <div style="font-size:3rem; margin-bottom:1rem;">🤖</div>
          <h2 style="font-size:1.5rem; font-weight:800; margin-bottom:0.5rem;">AI Assistant Restricted</h2>
          <p style="color:var(--text-secondary); margin-bottom:1.5rem;">
            Please log in to query your private documents with on-device AI.
          </p>
          <div style="display:flex; justify-content:center; gap:1rem;">
            <button id="lock-btn-login" class="btn btn-primary">Log In</button>
            <button id="lock-btn-register" class="btn btn-outline">Sign Up</button>
          </div>
        </div>
      `;
      document.getElementById("lock-btn-login").addEventListener("click", () => openAuthModal("login"));
      document.getElementById("lock-btn-register").addEventListener("click", () => openAuthModal("register"));
    }
    return;
  }

  const form = document.getElementById("ai-chat-form");
  const input = document.getElementById("ai-chat-input");
  const history = document.getElementById("ai-chat-history");

  if (!form) return;

  // Plan entitlement check
  if (user.plan_type !== "PREMIUM") {
    const notice = document.createElement("div");
    notice.className = "alert alert-info";
    notice.style.marginBottom = "1.5rem";
    notice.innerHTML = `
      <span>ℹ️</span>
      <div>
        <strong>FREE Plan Notice:</strong> On-device Semantic Vector Search & Local LLM Q&A are reserved for <strong>PREMIUM</strong> accounts. Keyword search (FTS5) is available for all files in your vault.
      </div>
    `;
    form.parentNode.insertBefore(notice, form);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = input.value.trim();
    if (!prompt) return;

    // Append user query
    const userMsg = document.createElement("div");
    userMsg.className = "card";
    userMsg.style.marginBottom = "1rem";
    userMsg.style.borderLeft = "4px solid var(--accent-cyan)";
    userMsg.innerHTML = `<strong style="color:var(--accent-cyan);">You:</strong> <p style="margin-top:0.25rem;">${prompt}</p>`;
    history.appendChild(userMsg);
    input.value = "";

    // Loading indicator
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "card";
    loadingMsg.style.marginBottom = "1rem";
    loadingMsg.innerHTML = `<em style="color:var(--text-muted);">Querying local on-device search index...</em>`;
    history.appendChild(loadingMsg);
    history.scrollTop = history.scrollHeight;

    try {
      const result = await api.queryAI(prompt);
      loadingMsg.remove();

      const botMsg = document.createElement("div");
      botMsg.className = "card";
      botMsg.style.marginBottom = "1rem";

      if (!result.has_sufficient_evidence) {
        botMsg.style.borderLeft = "4px solid var(--accent-warning)";
        botMsg.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:var(--accent-warning);">CipherQ Search Engine:</strong>
            <span class="badge badge-warning">Zero Evidence Found</span>
          </div>
          <p style="margin-top:0.75rem; color:var(--text-secondary);">${result.answer}</p>
          <p style="font-size:0.85rem; color:var(--text-muted); margin-top:0.5rem;">
            Tip: Make sure you have clicked <strong>"⚡ Index for AI"</strong> on your uploaded files in the Vault tab.
          </p>
        `;
      } else {
        botMsg.style.borderLeft = "4px solid var(--accent-cyan)";
        const citationsHtml = (result.citations || []).map(c => `
          <div style="background:rgba(28,37,65,0.6); border:1px solid var(--border-color); border-radius:4px; padding:0.5rem 0.75rem; margin-top:0.5rem; font-size:0.85rem;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="color:var(--accent-cyan); font-weight:600;">📄 ${c.filename} (Page ${c.page_number})</span>
              <span class="badge ${c.match_type.includes('SEMANTIC') ? 'badge-premium' : 'badge-free'}">${c.match_type}</span>
            </div>
            <div style="color:var(--text-secondary); margin-top:0.25rem; font-style:italic;">"${c.snippet}"</div>
          </div>
        `).join("");

        botMsg.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:var(--accent-cyan-light);">CipherQ Local Search (${result.mode_used}):</strong>
            <span class="badge badge-success">Local In-Memory</span>
          </div>
          <p style="margin-top:0.75rem; white-space:pre-wrap; line-height:1.6;">${result.answer}</p>
          <div style="margin-top:1rem; border-top:1px solid rgba(72,202,228,0.1); padding-top:0.5rem;">
            <small style="color:var(--text-muted); display:block; margin-bottom:0.25rem;">Grounded Source Citations (${result.citations.length}):</small>
            ${citationsHtml}
          </div>
        `;
      }

      history.appendChild(botMsg);
      history.scrollTop = history.scrollHeight;

    } catch (err) {
      loadingMsg.remove();
      const errorMsg = document.createElement("div");
      errorMsg.className = "card";
      errorMsg.style.marginBottom = "1rem";
      errorMsg.style.borderLeft = "4px solid var(--accent-danger)";
      errorMsg.innerHTML = `
        <strong style="color:var(--accent-danger);">Query Error:</strong>
        <p style="margin-top:0.4rem;">${err.message || "Failed to execute local search."}</p>
      `;
      history.appendChild(errorMsg);
      history.scrollTop = history.scrollHeight;
    }
  });
}

document.addEventListener("DOMContentLoaded", initApp);
