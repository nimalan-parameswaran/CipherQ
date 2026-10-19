import { api } from "./api.js";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[char]));
const isAiPlan = (plan) => ["VAULT_AI", "PREMIUM", "CREATOR"].includes(plan);
const isGreeting = (query) => /^(hi|hello|hey|hiya|good morning|good afternoon|good evening|how are you)[!.?,\s]*$/i.test(query.trim());

function applyTheme(theme) {
  const selected = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = selected;
  localStorage.setItem("cipherq-theme", selected);
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.textContent = selected === "dark" ? "☀ Light" : "☾ Dark";
    button.setAttribute("aria-label", `Switch to ${selected === "dark" ? "light" : "dark"} theme`);
  });
}

function setupThemeToggle() {
  const existing = document.querySelector("[data-theme-toggle]");
  if (existing) {
    existing.onclick = () => applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
    return;
  }

  const host = document.body.classList.contains("workspace-body")
    ? document.querySelector(".workspace-top .nav-actions")
    : document.querySelector(".site-header .nav-actions");
  if (!host) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-outline btn-sm theme-toggle";
  button.dataset.themeToggle = "true";
  host.prepend(button);
  button.onclick = () => applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
  applyTheme(document.body.dataset.theme || "light");
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
  return `${parseFloat((bytes / (1000 ** index)).toFixed(2))} ${units[index]}`;
}

function authLock(title, copy, icon = "Q") {
  const main = document.querySelector("main");
  if (!main) return;
  main.innerHTML = `
    <div class="card auth-lock-card">
      <span class="feature-number">${icon}</span>
      <h2>${title}</h2>
      <p class="muted">${copy}</p>
      <div class="hero-actions" style="justify-content:center;margin-top:24px">
        <button id="lock-btn-login" class="btn btn-primary">Log in</button>
        <button id="lock-btn-register" class="btn btn-outline">Create account</button>
      </div>
    </div>`;
  document.getElementById("lock-btn-login")?.addEventListener("click", () => openAuthModal("login"));
  document.getElementById("lock-btn-register")?.addEventListener("click", () => openAuthModal("register"));
}

function ensureAuthModal() {
  if (document.getElementById("auth-modal")) return;
  document.body.insertAdjacentHTML("beforeend", `
    <div id="auth-modal" class="modal-backdrop" style="display:none">
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
        <div class="modal-header">
          <div class="modal-heading">
            <div class="auth-modal-mark" aria-hidden="true">Q</div>
            <div>
              <div class="modal-kicker">Private workspace</div>
              <div class="modal-title" id="auth-modal-title">Sign in to CipherQ</div>
            </div>
          </div>
          <button class="modal-close" id="auth-modal-close" aria-label="Close">&times;</button>
        </div>
        <div class="modal-tabs">
          <button type="button" class="modal-tab-btn active" id="tab-login">Log in</button>
          <button type="button" class="modal-tab-btn" id="tab-register">Create account</button>
        </div>
        <div class="modal-body">
          <p class="modal-intro" id="auth-modal-intro">Access your encrypted vault and local AI workspace.</p>
          <div id="auth-alert" class="alert alert-danger" style="display:none;margin-bottom:14px"></div>
          <form id="form-login">
            <div class="form-group">
              <label class="form-label" for="login-email">Email address</label>
              <input class="form-control" type="email" id="login-email" required autocomplete="username">
            </div>
            <div class="form-group">
              <label class="form-label" for="login-password">Password</label>
              <input class="form-control" type="password" id="login-password" required autocomplete="current-password">
            </div>
            <button class="btn btn-primary" id="btn-submit-login" type="submit" style="width:100%;margin-top:8px">Log in to vault</button>
          </form>
          <form id="form-register" style="display:none">
            <div class="form-group">
              <label class="form-label" for="reg-email">Email address</label>
              <input class="form-control" type="email" id="reg-email" required autocomplete="username">
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-password">Password</label>
              <input class="form-control" type="password" id="reg-password" minlength="10" required autocomplete="new-password">
              <div class="form-hint">Use at least 10 characters for your vault account.</div>
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-plan">Plan</label>
              <select class="form-control" id="reg-plan">
                <option value="FREE">Free · 1 GB</option>
                <option value="PRIVATE_VAULT">Private Vault · 5 GB</option>
                <option value="VAULT_AI">Vault + AI · 5 GB + local AI</option>
              </select>
            </div>
            <button class="btn btn-primary" id="btn-submit-register" type="submit" style="width:100%;margin-top:8px">Create account</button>
          </form>
        </div>
      </div>
    </div>`);

  const loginTab = document.getElementById("tab-login");
  const registerTab = document.getElementById("tab-register");
  const loginForm = document.getElementById("form-login");
  const registerForm = document.getElementById("form-register");
  const title = document.getElementById("auth-modal-title");
  const intro = document.getElementById("auth-modal-intro");
  const alert = document.getElementById("auth-alert");

  const setMode = (mode) => {
    const login = mode === "login";
    loginTab.classList.toggle("active", login);
    registerTab.classList.toggle("active", !login);
    loginForm.style.display = login ? "block" : "none";
    registerForm.style.display = login ? "none" : "block";
    title.textContent = login ? "Sign in to CipherQ" : "Create your CipherQ account";
    intro.textContent = login
      ? "Access your encrypted vault and local AI workspace."
      : "Create a private workspace for encrypted files and on-device intelligence.";
    alert.style.display = "none";
  };

  loginTab.addEventListener("click", () => setMode("login"));
  registerTab.addEventListener("click", () => setMode("register"));
  document.getElementById("auth-modal-close").addEventListener("click", () => {
    document.getElementById("auth-modal").style.display = "none";
  });
  document.getElementById("auth-modal").addEventListener("click", (event) => {
    if (event.target.id === "auth-modal") event.target.style.display = "none";
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("btn-submit-login");
    try {
      button.disabled = true;
      button.textContent = "Authenticating…";
      await api.login(
        document.getElementById("login-email").value.trim(),
        document.getElementById("login-password").value
      );
      window.location.href = "dashboard.html";
    } catch (error) {
      alert.textContent = error.message || "Login failed.";
      alert.style.display = "block";
    } finally {
      button.disabled = false;
      button.textContent = "Log in to vault";
    }
  });

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("btn-submit-register");
    try {
      button.disabled = true;
      button.textContent = "Creating account…";
      const email = document.getElementById("reg-email").value.trim();
      const password = document.getElementById("reg-password").value;
      await api.register(email, password, document.getElementById("reg-plan").value);
      await api.login(email, password);
      window.location.href = "dashboard.html";
    } catch (error) {
      alert.textContent = error.message || "Registration failed.";
      alert.style.display = "block";
    } finally {
      button.disabled = false;
      button.textContent = "Create account";
    }
  });
}

export function openAuthModal(mode = "login") {
  ensureAuthModal();
  document.getElementById(mode === "register" ? "tab-register" : "tab-login").click();
  const alert = document.getElementById("auth-alert");
  if (api.configurationError) {
    alert.textContent = api.configurationError;
    alert.style.display = "block";
  }
  document.getElementById("auth-modal").style.display = "flex";
}

function updateNavbar(user) {
  // Sync all user displays and plan badges on the page
  const userDisplays = document.querySelectorAll("#user-display");
  const planBadges = document.querySelectorAll("#plan-badge");
  const sidebarUser = document.getElementById("sidebar-user");

  if (user) {
    userDisplays.forEach((el) => { el.textContent = user.email; });
    planBadges.forEach((el) => {
      el.textContent = user.plan_type;
      el.className = `badge ${user.plan_type !== "FREE" ? "badge-premium" : "badge-free"}`;
    });
    if (sidebarUser) sidebarUser.textContent = user.email;

    // Attach click handler to all logout buttons
    document.querySelectorAll("#btn-nav-logout").forEach((btn) => {
      btn.onclick = async () => {
        await api.logout();
        window.location.href = "index.html";
      };
    });
  }

  // Handle public landing page navbar (.nav-actions)
  if (!document.body.classList.contains("workspace-body")) {
    const actions = document.querySelector(".nav-actions");
    if (!actions) return;
    if (user) {
      actions.innerHTML = `
        <span class="nav-user" id="user-display">${escapeHtml(user.email)}</span>
        <span class="badge ${user.plan_type !== "FREE" ? "badge-premium" : "badge-free"}" id="plan-badge">${escapeHtml(user.plan_type)}</span>
        <a class="btn btn-outline btn-sm" href="dashboard.html">Workspace</a>
        <button class="btn btn-dark btn-sm" id="btn-nav-logout">Log out</button>`;
      document.getElementById("btn-nav-logout")?.addEventListener("click", async () => {
        await api.logout();
        window.location.href = "index.html";
      });
    } else {
      actions.innerHTML = `
        <button id="btn-nav-login" class="btn btn-outline btn-sm">Log in</button>
        <button id="btn-nav-register" class="btn btn-dark btn-sm">Get started</button>`;
      document.getElementById("btn-nav-login")?.addEventListener("click", () => openAuthModal("login"));
      document.getElementById("btn-nav-register")?.addEventListener("click", () => openAuthModal("register"));
    }
  }
}

function setupMobileNav() {
  // Landing page mobile menu
  const button = document.getElementById("mobile-menu");
  const links = document.getElementById("site-links");
  if (button && links) {
    button.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      button.setAttribute("aria-expanded", String(open));
    });
  }

  // Workspace mobile drawer toggle
  const workspaceToggle = document.getElementById("mobile-sidebar-toggle");
  const sidebar = document.getElementById("workspace-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");

  if (workspaceToggle && sidebar && backdrop) {
    const toggleSidebar = () => {
      const isOpen = sidebar.classList.toggle("drawer-open");
      backdrop.classList.toggle("active", isOpen);
      workspaceToggle.setAttribute("aria-expanded", String(isOpen));
    };

    workspaceToggle.addEventListener("click", toggleSidebar);
    backdrop.addEventListener("click", toggleSidebar);
  }
}

async function initDashboard(user) {
  if (!user) {
    authLock("Encrypted Vault Locked", "Log in to view your dashboard, storage quota, and recent files.");
    return;
  }

  const [usage, files] = await Promise.all([
    api.getUsage().catch(() => null),
    api.listFiles().catch(() => [])
  ]);

  const used = usage?.storage_bytes_used || 0;
  const quota = usage?.storage_quota_bytes || 1000000000;
  const percentage = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0;

  // Header Greeting
  const name = document.getElementById("user-badge");
  if (name) name.textContent = user.email;

  // Storage Metric
  const meter = document.getElementById("storage-meter-fill");
  if (meter) meter.style.width = `${percentage}%`;

  const text = document.getElementById("storage-text");
  if (text) text.textContent = `${formatBytes(used)} of ${formatBytes(quota)} used (${percentage}%)`;

  const storageDetail = document.getElementById("storage-detail");
  if (storageDetail) {
    storageDetail.textContent = `${formatBytes(Math.max(0, quota - used))} remaining in vault`;
  }

  // Plan Metric
  const plan = document.getElementById("dashboard-plan");
  if (plan) plan.textContent = user.plan_type;

  // AI Capability Metric
  const ai = document.getElementById("ai-status-text");
  if (ai) {
    ai.textContent = isAiPlan(user.plan_type)
      ? "Semantic Vector Search"
      : "Keyword Search included";
  }

  const aiAllowance = document.getElementById("ai-allowance-meta");
  if (aiAllowance) {
    aiAllowance.textContent = isAiPlan(user.plan_type)
      ? (usage ? `${usage.ai_queries_today} / ${usage.ai_daily_limit} queries today` : "100 queries / day")
      : "FTS5 Keyword Search (Local)";
  }

  // Stored Files Metric (Derived from real backend files array)
  const fileCount = document.getElementById("dashboard-file-count");
  if (fileCount) {
    const count = files?.length || 0;
    fileCount.textContent = `${count} ${count === 1 ? "file" : "files"}`;
  }

  const indexedCount = document.getElementById("dashboard-indexed-count");
  if (indexedCount) {
    const indexed = files?.filter(f => f.is_indexed)?.length || 0;
    indexedCount.textContent = `${indexed} indexed for AI`;
  }

  // Recent Files Table
  const recent = document.getElementById("recent-files");
  if (recent) {
    if (files?.length) {
      recent.innerHTML = files.slice(0, 5).map((file) => `
        <tr>
          <td data-label="File">
            <div class="file-cell">
              <div class="file-icon">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
              </div>
              <div>
                <span class="file-name">${escapeHtml(file.original_name)}</span>
                <span class="file-meta">SHA256 ${escapeHtml((file.sha256_hash || "Verified").slice(0, 16))}…</span>
              </div>
            </div>
          </td>
          <td data-label="Size">${formatBytes(file.file_size_bytes)}</td>
          <td data-label="Status">
            <span class="badge ${file.is_indexed ? "badge-success" : "badge-free"}">
              ${file.is_indexed ? "Indexed" : "Stored"}
            </span>
          </td>
          <td data-label="Created">${new Date(file.created_at).toLocaleDateString()}</td>
          <td data-label="Action" style="text-align:right">
            <button class="btn btn-outline btn-sm recent-download-btn" data-id="${escapeHtml(file.id)}" data-name="${escapeHtml(file.original_name)}">Download</button>
          </td>
        </tr>`).join("");

      recent.querySelectorAll(".recent-download-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          try {
            await api.downloadFile(btn.dataset.id, btn.dataset.name);
          } catch (e) {
            window.alert(e.message);
          } finally {
            btn.disabled = false;
          }
        });
      });
    } else {
      recent.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:28px">No files in your vault yet.</td></tr>`;
    }
  }
}

function setupDropzone() {
  const zone = document.getElementById("file-dropzone");
  const input = document.getElementById("file-input");
  const browseTrigger = document.getElementById("btn-browse-trigger");

  if (!zone || !input) return;

  if (browseTrigger) {
    browseTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      input.click();
    });
  }

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("dragover");
    if (event.dataTransfer.files[0]) handleUpload(event.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files[0]) handleUpload(input.files[0]);
    input.value = "";
  });
}

// Cached files for client-side search & filtering in the Vault
let vaultFilesCache = [];
let vaultActiveFilter = "all";
let vaultSearchQuery = "";

function applyVaultFilter() {
  const container = document.getElementById("file-list-body");
  const counter = document.getElementById("vault-counter");
  if (!container) return;

  const query = vaultSearchQuery.toLowerCase().trim();
  const filtered = vaultFilesCache.filter((file) => {
    const matchesSearch = !query || file.original_name.toLowerCase().includes(query);
    if (!matchesSearch) return false;
    if (vaultActiveFilter === "indexed") return Boolean(file.is_indexed);
    if (vaultActiveFilter === "unindexed") return !file.is_indexed;
    return true;
  });

  if (counter) {
    counter.textContent = vaultFilesCache.length
      ? `Showing ${filtered.length} of ${vaultFilesCache.length} files`
      : "";
  }

  if (!filtered.length) {
    if (vaultFilesCache.length > 0) {
      container.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:35px">No files match the selected filter.</td></tr>`;
    } else {
      // Must exactly contain this text for E2E tests
      container.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:35px">No encrypted files found in your vault. Upload a file above to begin.</td></tr>`;
    }
    return;
  }

  container.innerHTML = filtered.map((file) => `
    <tr id="row-${escapeHtml(file.id)}">
      <td data-label="File">
        <div class="file-cell">
          <div class="file-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
          </div>
          <div>
            <span class="file-name">${escapeHtml(file.original_name)}</span>
            <span class="file-meta">SHA256 ${escapeHtml((file.sha256_hash || "Verified").slice(0, 16))}…</span>
          </div>
        </div>
      </td>
      <td data-label="Size">${formatBytes(file.file_size_bytes)}</td>
      <td data-label="Indexing">
        <span class="badge badge-vault">Encrypted Vault</span>
        <span class="badge ${file.is_indexed ? "badge-success" : "badge-free"}">
          ${file.is_indexed ? "Indexed" : "Not indexed"}
        </span>
      </td>
      <td data-label="Created">${new Date(file.created_at).toLocaleDateString()}</td>
      <td data-label="Actions">
        <div class="table-actions">
          ${file.is_indexed
            ? `<button class="btn btn-outline btn-sm unindex-btn" data-id="${escapeHtml(file.id)}">Remove index</button>`
            : `<button class="btn btn-primary btn-sm index-btn" data-id="${escapeHtml(file.id)}">Index</button>`}
          <button class="btn btn-outline btn-sm download-btn" data-id="${escapeHtml(file.id)}" data-name="${escapeHtml(file.original_name)}">Download</button>
          <button class="btn btn-danger btn-sm delete-btn" data-id="${escapeHtml(file.id)}">Delete</button>
        </div>
      </td>
    </tr>`).join("");

  container.querySelectorAll(".index-btn, .unindex-btn").forEach((button) =>
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        if (button.classList.contains("index-btn")) await api.indexFile(button.dataset.id);
        else await api.unindexFile(button.dataset.id);
        await renderFileList(container);
      } catch (error) {
        button.disabled = false;
        window.alert(error.message);
      }
    })
  );

  container.querySelectorAll(".download-btn").forEach((button) =>
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api.downloadFile(button.dataset.id, button.dataset.name);
      } catch (error) {
        window.alert(error.message);
      } finally {
        button.disabled = false;
      }
    })
  );

  container.querySelectorAll(".delete-btn").forEach((button) =>
    button.addEventListener("click", async () => {
      if (!window.confirm("Delete this file from your vault?")) return;
      button.disabled = true;
      try {
        await api.deleteFile(button.dataset.id);
        await renderFileList(container);
      } catch (error) {
        button.disabled = false;
        window.alert(error.message);
      }
    })
  );
}

async function renderFileList(container) {
  if (!container) return;
  container.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:28px">Loading your encrypted files…</td></tr>`;
  try {
    const files = await api.listFiles();
    vaultFilesCache = files || [];
    applyVaultFilter();
  } catch (error) {
    container.innerHTML = `<tr><td colspan="5" class="alert alert-danger">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function handleUpload(file) {
  const zone = document.getElementById("file-dropzone");
  const original = zone.innerHTML;
  zone.innerHTML = `
    <strong>Uploading ${escapeHtml(file.name)}</strong>
    <p id="upload-status-text" class="muted">Streaming and encrypting (0%)…</p>
    <div class="progress" style="max-width:320px;margin:12px auto"><span id="upload-progress-fill" style="width:0%"></span></div>`;

  try {
    await api.uploadFile(file, (percent) => {
      const status = document.getElementById("upload-status-text");
      const fill = document.getElementById("upload-progress-fill");
      if (status) status.textContent = `Streaming and encrypting (${percent}%)…`;
      if (fill) fill.style.width = `${percent}%`;
    });
    zone.innerHTML = `<strong style="color:var(--cq-emerald)">Successfully encrypted and committed to vault!</strong>`;
    setTimeout(() => {
      zone.innerHTML = original;
      setupDropzone();
      renderFileList(document.getElementById("file-list-body"));
    }, 900);
  } catch (error) {
    zone.innerHTML = `
      <div class="alert alert-danger" style="margin:10px auto;max-width:480px">
        <strong>Upload failed.</strong> ${escapeHtml(error.message)}
        <div style="margin-top:10px">
          <button class="btn btn-outline btn-sm" id="btn-reset-dropzone">Dismiss</button>
        </div>
      </div>`;
    document.getElementById("btn-reset-dropzone")?.addEventListener("click", () => {
      zone.innerHTML = original;
      setupDropzone();
    });
  }
}

async function initFiles(user) {
  if (!user) {
    authLock("Vault Access Restricted", "Log in to upload, download, index, or delete encrypted vault files.", "V");
    return;
  }

  setupDropzone();

  // Search input handler
  const searchInput = document.getElementById("vault-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      vaultSearchQuery = e.target.value;
      applyVaultFilter();
    });
  }

  // Filter pills handler
  const filterPills = document.querySelectorAll(".filter-pill");
  filterPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      filterPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      vaultActiveFilter = pill.dataset.filter || "all";
      applyVaultFilter();
    });
  });

  await renderFileList(document.getElementById("file-list-body"));
}

async function initAIChat(user) {
  if (!user) {
    authLock("The assistant is private", "Log in to ask questions over your authorized local documents.", "AI");
    return;
  }

  const form = document.getElementById("ai-chat-form");
  const input = document.getElementById("ai-chat-input");
  const history = document.getElementById("ai-chat-history");
  if (!form || !input || !history) return;
  const clearChatButton = document.getElementById("btn-clear-chat");

  // Local AI Status Banner
  const statusText = document.getElementById("ai-engine-status-text");
  const quotaText = document.getElementById("ai-engine-quota-text");
  const statusDot = document.getElementById("ai-engine-dot");

  const usage = await api.getUsage().catch(() => null);

  if (isAiPlan(user.plan_type)) {
    if (statusText) statusText.textContent = `${user.plan_type}: Hybrid Semantic Vector + Local Gemma Pipeline Active`;
    if (quotaText && usage) quotaText.textContent = `${usage.ai_queries_today} / ${usage.ai_daily_limit} queries today`;
  } else if (user.plan_type === "PRIVATE_VAULT") {
    document.getElementById("ai-plan-notice")?.classList.remove("sr-only");
    if (statusText) statusText.textContent = "Private Vault: SQLite FTS5 Keyword Search";
    if (quotaText) quotaText.textContent = "AI assistant available on Vault + AI";
    if (statusDot) statusDot.classList.add("warning");
  } else {
    document.getElementById("ai-plan-notice")?.classList.remove("sr-only");
    if (statusText) statusText.textContent = "Free Tier: SQLite FTS5 Keyword Search (Local Retrieval)";
    if (quotaText) quotaText.textContent = "Keyword search only";
    if (statusDot) statusDot.classList.add("warning");
  }

  // Helpful Empty State with Example Prompts
  history.innerHTML = `
    <div class="chat-empty-state">
      <div class="chat-empty-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3v3m6.364 1.636-2.121 2.121M21 12h-3m1.636 6.364-2.121-2.121M12 21v-3M4.636 18.364l2.121-2.121M3 12h3M4.636 5.636l2.121 2.121"></path>
          <circle cx="12" cy="12" r="4"></circle>
        </svg>
      </div>
      <div class="chat-empty-title">Ask your documents</div>
      <p class="chat-empty-copy">
        Queries search your authorized local vault index and synthesize answers on-device.
        <strong style="display:block;margin-top:6px;color:var(--cq-text)">Note: Files must be indexed in your Vault first to be searchable.</strong>
      </p>
      <div class="chat-prompt-chips">
        <button type="button" class="prompt-chip" data-query="Summarize the key findings across my indexed documents.">
          <span>Summarize the key findings across my indexed documents</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
        </button>
        <button type="button" class="prompt-chip" data-query="What are the main requirements and specifications?">
          <span>What are the main requirements and specifications?</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
        </button>
        <button type="button" class="prompt-chip" data-query="List security controls and compliance guidelines in my notes.">
          <span>List security controls and compliance guidelines in my notes</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
        </button>
      </div>
    </div>`;

  const renderEmptyState = () => {
    history.innerHTML = `
      <div class="chat-empty-state">
        <div class="chat-empty-icon">Q</div>
        <div class="chat-empty-title">Ask your documents</div>
        <p class="chat-empty-copy">Search your indexed files and get a concise answer grounded in your private workspace.</p>
        <div class="chat-prompt-chips">
          <button type="button" class="prompt-chip" data-query="Who is the author of this document?"><span>Who is the author of this document?</span></button>
          <button type="button" class="prompt-chip" data-query="Summarize the key points in this document."><span>Summarize the key points</span></button>
          <button type="button" class="prompt-chip" data-query="What are the most important requirements?"><span>Find the important requirements</span></button>
        </div>
      </div>`;
    history.querySelectorAll(".prompt-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        input.value = chip.dataset.query || "";
        input.focus();
      });
    });
  };

  clearChatButton?.addEventListener("click", () => {
    if (form.dataset.busy === "true") return;
    renderEmptyState();
    input.value = "";
    input.focus();
  });

  history.querySelectorAll(".prompt-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.query || "";
      input.focus();
    });
  });

  let lastQuery = "";

  const submitQuery = async (queryText) => {
    const query = (queryText || input.value).trim();
    if (!query || form.dataset.busy === "true") return;

    form.dataset.busy = "true";
    lastQuery = query;
    input.value = "";

    // Clear empty state on first message
    const emptyState = history.querySelector(".chat-empty-state");
    if (emptyState) emptyState.remove();

    // User Message
    const userMsg = document.createElement("div");
    userMsg.className = "message user";
    userMsg.innerHTML = `
      <div class="message-label">You</div>
      <div class="message-content">${escapeHtml(query).replace(/\n/g, "<br>")}</div>`;
    history.appendChild(userMsg);

    // Loading Assistant Message
    const loading = document.createElement("div");
    loading.className = "message assistant";
    const conversationalQuery = isGreeting(query);
    loading.innerHTML = `
      <div class="message-header">
        <span class="message-label">CipherQ</span>
        <span class="badge badge-meta">${conversationalQuery ? "RESPONDING" : "SEARCHING YOUR VAULT"}</span>
      </div>
      <div class="muted" style="display:flex;align-items:center">
        <span class="spinner-dots"><span></span><span></span><span></span></span>
        <span>${conversationalQuery ? "Preparing a response…" : "Retrieving relevant evidence…"}</span>
      </div>`;
    history.appendChild(loading);
    history.scrollTop = history.scrollHeight;

    try {
      const result = await api.queryAI(query);
      loading.remove();

      const answerMsg = document.createElement("div");
      answerMsg.className = "message assistant";
      const conversationResponse = result.response_kind === "CONVERSATION" || conversationalQuery;
      const outOfScopeResponse = result.response_kind === "OUT_OF_SCOPE";

      // Keep greetings conversational even when an older backend deployment
      // returns the pre-conversation retrieval response contract.
      if (conversationalQuery && result.response_kind !== "CONVERSATION") {
        result.answer = "Hi! I’m CipherQ. Ask me anything about your indexed documents when you’re ready.";
        result.citations = [];
        result.has_sufficient_evidence = true;
      }

      let citationsHtml = "";
      if (!conversationResponse && result.citations && result.citations.length > 0) {
        citationsHtml = `
          <details class="citations-container">
            <summary class="citations-title">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
              </svg>
              <span>Sources (${result.citations.length})</span>
            </summary>
            <div class="citations-list">
              ${result.citations.map((c) => `
                <div class="citation-card">
                  <div class="citation-header">
                    <span class="citation-source">${escapeHtml(c.filename)} &bull; Page ${c.page_number}</span>
                    <span class="badge badge-meta" style="font-size:0.62rem">${escapeHtml(c.match_type || "Match")}</span>
                  </div>
                  <div class="citation-snippet">${escapeHtml(c.snippet)}</div>
                </div>`).join("")}
            </div>
          </details>`;
      }

      const evidenceWarning = result.has_sufficient_evidence
        || conversationResponse
        || outOfScopeResponse
        ? ""
        : `<div class="message-evidence-alert alert-warning">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
             <span>I couldn’t find enough evidence in your indexed documents. Index a file in the Vault, then try again.</span>
           </div>`;

      answerMsg.innerHTML = `
        <div class="message-header">
          <span class="message-label">CipherQ</span>
          <span class="badge badge-meta">${conversationResponse ? "READY TO HELP" : outOfScopeResponse ? "VAULT-FOCUSED" : "GROUNDED ANSWER"}</span>
        </div>
        <div class="message-content">${escapeHtml(result.answer).replace(/\n/g, "<br>")}</div>
        ${evidenceWarning}
        ${citationsHtml}`;

      history.appendChild(answerMsg);
    } catch (error) {
      loading.remove();
      const failure = document.createElement("div");
      failure.className = "message assistant";
      failure.innerHTML = `
        <div class="message-header">
          <span class="message-label" style="color:var(--cq-danger)">Query error</span>
        </div>
        <div class="message-content" style="color:#f87171">${escapeHtml(error.message)}</div>
        <button type="button" class="btn btn-outline btn-sm btn-retry-query" style="margin-top:12px">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"></path><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M3 22v-6h6"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path></svg>
          <span>Retry query</span>
        </button>`;

      failure.querySelector(".btn-retry-query")?.addEventListener("click", () => {
        failure.remove();
        submitQuery(lastQuery);
      });

      history.appendChild(failure);
    } finally {
      form.dataset.busy = "false";
      history.scrollTop = history.scrollHeight;
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitQuery();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitQuery();
    }
  });
}

async function initAccount(user) {
  if (!user) {
    authLock("Account access is restricted", "Log in to view your plan and account details.");
    return;
  }

  // Overview metrics
  document.getElementById("account-email").textContent = user.email;
  document.getElementById("account-plan").textContent = user.plan_type;

  const usage = await api.getUsage();
  if (usage) {
    document.getElementById("account-quota").textContent = formatBytes(usage.storage_quota_bytes);
    document.getElementById("account-ai-limit").textContent = `${usage.ai_daily_limit} queries/day`;

    const storageMeta = document.getElementById("account-storage-meta");
    if (storageMeta) {
      const pct = Math.round((usage.storage_bytes_used / usage.storage_quota_bytes) * 100);
      storageMeta.textContent = `${formatBytes(usage.storage_bytes_used)} used (${pct}%)`;
    }
  }

  // Active Plan Highlighting on Plan Cards
  if (user.plan_type === "FREE") {
    const freeCard = document.getElementById("card-plan-free");
    if (freeCard) {
      freeCard.classList.add("active-plan");
      freeCard.insertAdjacentHTML("afterbegin", '<span class="current-plan-pill">Current plan</span>');
    }
    const freeAction = document.getElementById("plan-action-free");
    if (freeAction) {
      freeAction.innerHTML = '<button class="btn btn-outline" style="width:100%" disabled>Active plan</button>';
    }
  } else if (user.plan_type === "PRIVATE_VAULT" || user.plan_type === "VAULT_AI" || user.plan_type === "PREMIUM" || user.plan_type === "CREATOR") {
    const activeCardId = user.plan_type === "PRIVATE_VAULT" ? "card-plan-private-vault" : "card-plan-vault-ai";
    const activeActionId = user.plan_type === "PRIVATE_VAULT" ? "plan-action-private-vault" : "plan-action-vault-ai";
    const activeCard = document.getElementById(activeCardId);
    if (activeCard) {
      activeCard.classList.add("active-plan");
      activeCard.insertAdjacentHTML("afterbegin", '<span class="current-plan-pill">Current plan</span>');
    }
    const activeAction = document.getElementById(activeActionId);
    if (activeAction) {
      activeAction.innerHTML = '<button class="btn btn-outline" style="width:100%" disabled>Active plan</button>';
    }
  }

  // Development Plan Management Toggle
  const button = document.getElementById("btn-toggle-plan");
  if (!button) return;

  const target = user.plan_type === "FREE" ? "VAULT_AI" : "FREE";
  button.textContent = target === "VAULT_AI" ? "Upgrade to Vault + AI" : "Downgrade to Free";

  button.addEventListener("click", async () => {
    const token = window.prompt(`Enter administrative token to change ${user.email} to ${target}:`);
    if (!token) return;

    const alert = document.getElementById("plan-change-alert");
    try {
      await api.adminChangePlan(user.email, target, token, "account_page_admin_switch");
      alert.className = "alert alert-success";
      alert.textContent = `Plan updated to ${target}. Reloading…`;
      alert.style.display = "block";
      setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      alert.className = "alert alert-danger";
      alert.textContent = error.message;
      alert.style.display = "block";
    }
  });
}

async function initApp() {
  ensureAuthModal();
  let user;
  try {
    // Allow the browser a brief interval to expose a newly-issued
    // cross-origin cookie after a full-page navigation.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      user = await api.getMe();
      if (user) break;
      if (attempt < 2) {
        await new Promise((resolve) => setTimeout(resolve, 200 * (attempt + 1)));
      }
    }
  } catch (error) {
    const main = document.querySelector("main");
    if (main) {
      main.insertAdjacentHTML("afterbegin", `
        <div class="container section" role="alert">
          <div class="alert alert-danger">
            <strong>Backend unavailable.</strong> ${escapeHtml(error.message)}
          </div>
        </div>`);
    }
    updateNavbar(null);
    setupMobileNav();
    return;
  }
  updateNavbar(user);
  applyTheme(localStorage.getItem("cipherq-theme") || "light");
  setupThemeToggle();
  setupMobileNav();

  const page = location.pathname.split("/").pop() || "index.html";

  if (page === "index.html" || page === "") {
    document.querySelectorAll(".public-plan-action").forEach((button) =>
      button.addEventListener("click", () => openAuthModal(button.dataset.mode || "register"))
    );
    ["hero-get-started", "final-get-started"].forEach((id) =>
      document.getElementById(id)?.addEventListener("click", () => openAuthModal("register"))
    );
    return;
  }

  if (page === "dashboard.html") return initDashboard(user);
  if (page === "files.html") return initFiles(user);
  if (page === "ai-chat.html") return initAIChat(user);
  if (page === "account.html") return initAccount(user);
}

document.addEventListener("DOMContentLoaded", initApp);
