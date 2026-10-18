import { api } from "./api.js";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[char]));

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
  return `${parseFloat((bytes / (1000 ** index)).toFixed(2))} ${units[index]}`;
}

function authLock(title, copy, icon = "Q") {
  const main = document.querySelector("main");
  if (!main) return;
  main.innerHTML = `<div class="card auth-lock-card"><span class="feature-number">${icon}</span><h2>${title}</h2><p class="muted">${copy}</p><div class="hero-actions" style="justify-content:center"><button id="lock-btn-login" class="btn btn-primary">Log in</button><button id="lock-btn-register" class="btn btn-outline">Create account</button></div></div>`;
  document.getElementById("lock-btn-login").addEventListener("click", () => openAuthModal("login"));
  document.getElementById("lock-btn-register").addEventListener("click", () => openAuthModal("register"));
}

function ensureAuthModal() {
  if (document.getElementById("auth-modal")) return;
  document.body.insertAdjacentHTML("beforeend", `<div id="auth-modal" class="modal-backdrop" style="display:none"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title"><div class="modal-header"><div class="modal-title" id="auth-modal-title">Sign in to CipherQ</div><button class="modal-close" id="auth-modal-close" aria-label="Close">&times;</button></div><div class="modal-tabs"><button type="button" class="modal-tab-btn active" id="tab-login">Log in</button><button type="button" class="modal-tab-btn" id="tab-register">Create account</button></div><div class="modal-body"><div id="auth-alert" class="alert alert-danger" style="display:none"></div><form id="form-login"><div class="form-group"><label class="form-label" for="login-email">Email address</label><input class="form-control" type="email" id="login-email" required autocomplete="username"></div><div class="form-group"><label class="form-label" for="login-password">Password</label><input class="form-control" type="password" id="login-password" required autocomplete="current-password"></div><button class="btn btn-primary" id="btn-submit-login" type="submit" style="width:100%">Log in to vault</button></form><form id="form-register" style="display:none"><div class="form-group"><label class="form-label" for="reg-email">Email address</label><input class="form-control" type="email" id="reg-email" required autocomplete="username"></div><div class="form-group"><label class="form-label" for="reg-password">Password</label><input class="form-control" type="password" id="reg-password" minlength="10" required autocomplete="new-password"></div><div class="form-group"><label class="form-label" for="reg-plan">Plan</label><select class="form-control" id="reg-plan"><option value="FREE">Free · 1 GB</option><option value="PREMIUM">Premium · 5 GB + local AI</option></select></div><button class="btn btn-primary" id="btn-submit-register" type="submit" style="width:100%">Create account</button></form></div></div></div>`);
  const loginTab = document.getElementById("tab-login");
  const registerTab = document.getElementById("tab-register");
  const loginForm = document.getElementById("form-login");
  const registerForm = document.getElementById("form-register");
  const title = document.getElementById("auth-modal-title");
  const alert = document.getElementById("auth-alert");
  const setMode = (mode) => {
    const login = mode === "login";
    loginTab.classList.toggle("active", login); registerTab.classList.toggle("active", !login);
    loginForm.style.display = login ? "block" : "none"; registerForm.style.display = login ? "none" : "block";
    title.textContent = login ? "Sign in to CipherQ" : "Create your CipherQ account"; alert.style.display = "none";
  };
  loginTab.addEventListener("click", () => setMode("login"));
  registerTab.addEventListener("click", () => setMode("register"));
  document.getElementById("auth-modal-close").addEventListener("click", () => { document.getElementById("auth-modal").style.display = "none"; });
  document.getElementById("auth-modal").addEventListener("click", (event) => { if (event.target.id === "auth-modal") event.target.style.display = "none"; });
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault(); const button = document.getElementById("btn-submit-login");
    try { button.disabled = true; button.textContent = "Authenticating…"; await api.login(document.getElementById("login-email").value.trim(), document.getElementById("login-password").value); window.location.href = "dashboard.html"; }
    catch (error) { alert.textContent = error.message || "Login failed."; alert.style.display = "block"; }
    finally { button.disabled = false; button.textContent = "Log in to vault"; }
  });
  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault(); const button = document.getElementById("btn-submit-register");
    try { button.disabled = true; button.textContent = "Creating account…"; const email = document.getElementById("reg-email").value.trim(); const password = document.getElementById("reg-password").value; await api.register(email, password, document.getElementById("reg-plan").value); await api.login(email, password); window.location.href = "dashboard.html"; }
    catch (error) { alert.textContent = error.message || "Registration failed."; alert.style.display = "block"; }
    finally { button.disabled = false; button.textContent = "Create account"; }
  });
}

export function openAuthModal(mode = "login") {
  ensureAuthModal();
  document.getElementById(mode === "register" ? "tab-register" : "tab-login").click();
  document.getElementById("auth-modal").style.display = "flex";
}

function updateNavbar(user) {
  const actions = document.querySelector(".nav-actions");
  if (!actions) return;
  if (user) {
    const target = document.body.classList.contains("workspace-body") ? "account.html" : "dashboard.html";
    actions.innerHTML = `<span class="nav-user" id="user-display">${escapeHtml(user.email)}</span><span class="badge ${user.plan_type === "PREMIUM" ? "badge-premium" : "badge-free"}" id="plan-badge">${escapeHtml(user.plan_type)}</span><a class="btn btn-outline btn-sm" href="${target}">Workspace</a><button class="btn btn-dark btn-sm" id="btn-nav-logout">Log out</button>`;
    document.getElementById("btn-nav-logout").addEventListener("click", async () => { await api.logout(); window.location.href = "index.html"; });
  } else if (!document.body.classList.contains("workspace-body")) {
    actions.innerHTML = `<button id="btn-nav-login" class="btn btn-outline btn-sm">Log in</button><button id="btn-nav-register" class="btn btn-dark btn-sm">Get started</button>`;
    document.getElementById("btn-nav-login").addEventListener("click", () => openAuthModal("login"));
    document.getElementById("btn-nav-register").addEventListener("click", () => openAuthModal("register"));
  }
}

function setupMobileNav() {
  const button = document.getElementById("mobile-menu");
  const links = document.getElementById("site-links");
  if (!button || !links) return;
  button.addEventListener("click", () => { const open = links.classList.toggle("open"); button.setAttribute("aria-expanded", String(open)); });
}

async function initDashboard(user) {
  if (!user) { authLock("Encrypted Vault Locked", "Log in to view your dashboard, storage quota, and recent files."); return; }
  const usage = await api.getUsage();
  const files = await api.listFiles();
  const used = usage?.storage_bytes_used || 0; const quota = usage?.storage_quota_bytes || 1000000000; const percentage = Math.min(100, Math.round((used / quota) * 100));
  const name = document.getElementById("user-badge"); if (name) name.textContent = user.email;
  const meter = document.getElementById("storage-meter-fill"); if (meter) meter.style.width = `${percentage}%`;
  const text = document.getElementById("storage-text"); if (text) text.textContent = `${formatBytes(used)} of ${formatBytes(quota)} used (${percentage}%)`;
  const plan = document.getElementById("dashboard-plan"); if (plan) plan.textContent = user.plan_type;
  const ai = document.getElementById("ai-status-text"); if (ai) ai.textContent = user.plan_type === "PREMIUM" ? "Semantic Vector Search" : "Keyword Search included";
  const recent = document.getElementById("recent-files");
  if (recent) recent.innerHTML = files?.length ? files.slice(0, 5).map((file) => `<tr><td data-label="File"><span class="file-name">${escapeHtml(file.original_name)}</span></td><td data-label="Size">${formatBytes(file.file_size_bytes)}</td><td data-label="Status"><span class="badge ${file.is_indexed ? "badge-success" : "badge-free"}">${file.is_indexed ? "Indexed" : "Stored"}</span></td></tr>`).join("") : `<tr><td colspan="3" class="muted" style="text-align:center">No files in your vault yet.</td></tr>`;
}

function setupDropzone() {
  const zone = document.getElementById("file-dropzone"); const input = document.getElementById("file-input");
  if (!zone || !input) return;
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (event) => { event.preventDefault(); zone.classList.remove("dragover"); if (event.dataTransfer.files[0]) handleUpload(event.dataTransfer.files[0]); });
  input.addEventListener("change", () => { if (input.files[0]) handleUpload(input.files[0]); input.value = ""; });
}

async function renderFileList(container) {
  container.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center">Loading your encrypted files…</td></tr>`;
  let files;
  try { files = await api.listFiles(); } catch (error) { container.innerHTML = `<tr><td colspan="5" class="alert alert-danger">${escapeHtml(error.message)}</td></tr>`; return; }
  if (!files?.length) { container.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:35px">No encrypted files found in your vault. Upload a file above to begin.</td></tr>`; return; }
  container.innerHTML = files.map((file) => `<tr id="row-${escapeHtml(file.id)}"><td data-label="File"><span class="file-name">${escapeHtml(file.original_name)}</span><span class="file-meta">SHA256 ${escapeHtml((file.sha256_hash || "Verified").slice(0, 16))}…</span></td><td data-label="Size">${formatBytes(file.file_size_bytes)}</td><td data-label="Indexing"><span class="badge ${file.is_indexed ? "badge-success" : "badge-free"}">Encrypted Vault · ${file.is_indexed ? "Indexed" : "Not indexed"}</span></td><td data-label="Created">${new Date(file.created_at).toLocaleDateString()}</td><td data-label="Actions"><div class="table-actions">${file.is_indexed ? `<button class="btn btn-outline btn-sm unindex-btn" data-id="${escapeHtml(file.id)}">Remove index</button>` : `<button class="btn btn-primary btn-sm index-btn" data-id="${escapeHtml(file.id)}">Index</button>`}<button class="btn btn-outline btn-sm download-btn" data-id="${escapeHtml(file.id)}" data-name="${escapeHtml(file.original_name)}">Download</button><button class="btn btn-danger btn-sm delete-btn" data-id="${escapeHtml(file.id)}">Delete</button></div></td></tr>`).join("");
  container.querySelectorAll(".index-btn,.unindex-btn").forEach((button) => button.addEventListener("click", async () => { button.disabled = true; try { if (button.classList.contains("index-btn")) await api.indexFile(button.dataset.id); else await api.unindexFile(button.dataset.id); await renderFileList(container); } catch (error) { button.disabled = false; window.alert(error.message); } }));
  container.querySelectorAll(".download-btn").forEach((button) => button.addEventListener("click", async () => { button.disabled = true; try { await api.downloadFile(button.dataset.id, button.dataset.name); } catch (error) { window.alert(error.message); } finally { button.disabled = false; } }));
  container.querySelectorAll(".delete-btn").forEach((button) => button.addEventListener("click", async () => { if (!window.confirm("Delete this file from your vault?")) return; button.disabled = true; try { await api.deleteFile(button.dataset.id); await renderFileList(container); } catch (error) { button.disabled = false; window.alert(error.message); } }));
}

async function handleUpload(file) {
  const zone = document.getElementById("file-dropzone"); const original = zone.innerHTML;
  zone.innerHTML = `<strong>Uploading ${escapeHtml(file.name)}</strong><p id="upload-status-text">Streaming and encrypting (0%)…</p><div class="progress"><span id="upload-progress-fill" style="width:0%"></span></div>`;
  try { await api.uploadFile(file, (percent) => { const status = document.getElementById("upload-status-text"); const fill = document.getElementById("upload-progress-fill"); if (status) status.textContent = `Streaming and encrypting (${percent}%)…`; if (fill) fill.style.width = `${percent}%`; }); zone.innerHTML = `<strong style="color:var(--emerald)">Successfully encrypted and committed to vault!</strong>`; setTimeout(() => { zone.innerHTML = original; renderFileList(document.getElementById("file-list-body")); }, 900); }
  catch (error) { zone.innerHTML = `<div class="alert alert-danger"><strong>Upload failed.</strong> ${escapeHtml(error.message)} <button class="btn btn-outline btn-sm" id="btn-reset-dropzone">Dismiss</button></div>`; document.getElementById("btn-reset-dropzone").addEventListener("click", () => { zone.innerHTML = original; }); }
}

async function initFiles(user) {
  if (!user) { authLock("Vault Access Restricted", "Log in to upload, download, index, or delete encrypted vault files.", "V"); return; }
  setupDropzone(); await renderFileList(document.getElementById("file-list-body"));
}

async function initAIChat(user) {
  if (!user) { authLock("The assistant is private", "Log in to ask questions over your authorized local documents.", "AI"); return; }
  const form = document.getElementById("ai-chat-form"); const input = document.getElementById("ai-chat-input"); const history = document.getElementById("ai-chat-history"); if (!form) return;
  if (user.plan_type !== "PREMIUM") document.getElementById("ai-plan-notice")?.classList.remove("sr-only");
  const submit = async () => {
    const query = input.value.trim(); if (!query || form.dataset.busy === "true") return;
    form.dataset.busy = "true"; input.value = ""; const userMessage = document.createElement("div"); userMessage.className = "message user"; userMessage.innerHTML = `<div class="message-label">You</div><div>${escapeHtml(query).replace(/\n/g, "<br>")}</div>`; history.appendChild(userMessage);
    const loading = document.createElement("div"); loading.className = "message"; loading.innerHTML = `<div class="message-label">CipherQ</div><div class="muted">Searching your local index…</div>`; history.appendChild(loading); history.scrollTop = history.scrollHeight;
    try { const result = await api.queryAI(query); loading.remove(); const answer = document.createElement("div"); answer.className = "message"; answer.innerHTML = `<div class="message-label">CipherQ local assistant</div><div>${escapeHtml(result.answer).replace(/\n/g, "<br>")}</div>${result.has_sufficient_evidence ? "" : '<div class="muted" style="margin-top:9px;font-size:.8rem">No sufficient indexed evidence was found. Index a document in the Vault and try again.</div>'}`; history.appendChild(answer); }
    catch (error) { loading.remove(); const failure = document.createElement("div"); failure.className = "message"; failure.innerHTML = `<div class="message-label" style="color:var(--danger)">Query error</div><div>${escapeHtml(error.message)}</div>`; history.appendChild(failure); }
    finally { form.dataset.busy = "false"; history.scrollTop = history.scrollHeight; }
  };
  form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
  input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } });
}

async function initAccount(user) {
  if (!user) { authLock("Account access is restricted", "Log in to view your plan and account details."); return; }
  document.getElementById("account-email").textContent = user.email; document.getElementById("account-plan").textContent = user.plan_type;
  const usage = await api.getUsage(); if (usage) { document.getElementById("account-quota").textContent = formatBytes(usage.storage_quota_bytes); document.getElementById("account-ai-limit").textContent = `${usage.ai_daily_limit} queries/day`; }
  const button = document.getElementById("btn-toggle-plan"); if (!button) return;
  const target = user.plan_type === "PREMIUM" ? "FREE" : "PREMIUM"; button.textContent = target === "PREMIUM" ? "Upgrade to Premium" : "Downgrade to Free";
  button.addEventListener("click", async () => { const token = window.prompt(`Enter administrative token to change ${user.email} to ${target}:`); if (!token) return; const alert = document.getElementById("plan-change-alert"); try { await api.adminChangePlan(user.email, target, token, "account_page_admin_switch"); alert.className = "alert alert-success"; alert.textContent = `Plan updated to ${target}. Reloading…`; alert.style.display = "block"; setTimeout(() => window.location.reload(), 700); } catch (error) { alert.className = "alert alert-danger"; alert.textContent = error.message; alert.style.display = "block"; } });
}

async function initApp() {
  ensureAuthModal();
  const user = await api.getMe(); updateNavbar(user); setupMobileNav();
  const page = location.pathname.split("/").pop() || "index.html";
  if (page === "index.html" || page === "") { document.querySelectorAll(".public-plan-action").forEach((button) => button.addEventListener("click", () => openAuthModal(button.dataset.mode || "register"))); ["hero-get-started", "final-get-started"].forEach((id) => document.getElementById(id)?.addEventListener("click", () => openAuthModal("register"))); return; }
  if (page === "dashboard.html") return initDashboard(user);
  if (page === "files.html") return initFiles(user);
  if (page === "ai-chat.html") return initAIChat(user);
  if (page === "account.html") return initAccount(user);
}

document.addEventListener("DOMContentLoaded", initApp);
