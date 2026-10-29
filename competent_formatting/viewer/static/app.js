/* competent_formatting viewer frontend.
 *
 * The one behaviour worth guarding: switching profile (or reloading after a
 * recompile) must land on the same page at the same offset, so that `full` and
 * `clean` line up visually when the stripped macros do not change pagination.
 */
"use strict";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const UI = {
  state: null,
  docId: null,
  profile: null,
  scale: 1.0,
  logKind: "live",
  liveLines: [],
  renderToken: 0,
  native: false,
  pdfDoc: null,
};

const $ = (id) => document.getElementById(id);
const scroller = () => $("pdf-scroll");

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body;
  try { body = JSON.parse(text); } catch (_) { body = { raw: text }; }
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

const postJSON = (path, payload) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload || {}) });

/* ------------------------------------------------------------ scroll anchor */

function captureAnchor() {
  const box = scroller();
  const pages = [...document.querySelectorAll(".pdf-page")];
  if (!pages.length) return null;
  const top = box.scrollTop;
  for (let index = 0; index < pages.length; index++) {
    const page = pages[index];
    const end = page.offsetTop + page.offsetHeight;
    if (top < end) {
      return { page: index, frac: (top - page.offsetTop) / Math.max(1, page.offsetHeight) };
    }
  }
  return { page: pages.length - 1, frac: 0 };
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const pages = [...document.querySelectorAll(".pdf-page")];
  if (!pages.length) return;
  const page = pages[Math.min(anchor.page, pages.length - 1)];
  scroller().scrollTop = page.offsetTop + anchor.frac * page.offsetHeight;
}

/* ------------------------------------------------------------ pdf rendering */

/* Hand the PDF to the browser's own viewer.
 *
 * Canvas rendering gives us the per-page scroll anchor that keeps `full` and `clean` aligned,
 * but a canvas is a bitmap: no text selection, no hyperref links. This mode trades the anchor
 * for both, and costs nothing to maintain -- /api/pdf already serves inline application/pdf,
 * so the browser does the work. The canvas path stays the default.
 */
function renderNative() {
  const frame = $("pdf-native");
  const url = `/api/pdf/${UI.docId}/${UI.profile}?t=${Date.now()}`;
  if (frame.getAttribute("src") !== url) frame.setAttribute("src", url);
  $("pdf-pages").innerHTML = "";
  $("pdf-pages").hidden = true;
  frame.hidden = false;
  document.body.classList.add("native");
}

function hideNative() {
  const frame = $("pdf-native");
  frame.hidden = true;
  frame.removeAttribute("src");
  $("pdf-pages").hidden = false;
  document.body.classList.remove("native");
}

async function renderPdf(anchor) {
  if (!UI.docId || !UI.profile) return;
  if (UI.native) {
    UI.renderToken++;  // cancel any canvas render still walking pages
    renderNative();
    return;
  }
  hideNative();
  const token = ++UI.renderToken;
  const url = `/api/pdf/${UI.docId}/${UI.profile}?t=${Date.now()}`;
  const host = $("pdf-pages");

  let pdf;
  try {
    pdf = await pdfjsLib.getDocument({ url, withCredentials: false }).promise;
  } catch (error) {
    if (token !== UI.renderToken) return;
    host.innerHTML = `<p class="hint" style="color:var(--dim)">No PDF yet for
      <code>${UI.docId}/${UI.profile}</code>. Hit recompile.</p>`;
    return;
  }
  if (token !== UI.renderToken) return;
  UI.pdfDoc = pdf;

  // Lay out correctly-sized placeholders first so the scroll height (and thus
  // the restored anchor) is right before any canvas has painted.
  const viewports = [];
  for (let number = 1; number <= pdf.numPages; number++) {
    const page = await pdf.getPage(number);
    viewports.push(page.getViewport({ scale: UI.scale }));
  }
  if (token !== UI.renderToken) return;

  host.innerHTML = "";
  const holders = viewports.map((viewport) => {
    const holder = document.createElement("div");
    holder.className = "pdf-page";
    holder.style.width = `${Math.floor(viewport.width)}px`;
    holder.style.height = `${Math.floor(viewport.height)}px`;
    host.appendChild(holder);
    return holder;
  });
  restoreAnchor(anchor);

  const ratio = window.devicePixelRatio || 1;
  for (let index = 0; index < holders.length; index++) {
    if (token !== UI.renderToken) return;
    const page = await pdf.getPage(index + 1);
    const viewport = viewports[index];
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    await page.render({ canvasContext: context, viewport }).promise;
    if (token !== UI.renderToken) return;
    holders[index].appendChild(canvas);
  }
  restoreAnchor(anchor);
}

async function reloadPdf() { await renderPdf(captureAnchor()); }

/* ------------------------------------------------------------ toolbar */

function currentDoc() {
  return (UI.state?.documents || []).find((d) => d.id === UI.docId) || null;
}

function buildFor(docId, profile) {
  const doc = (UI.state?.documents || []).find((d) => d.id === docId);
  return (doc?.builds || []).find((b) => b.profile === profile) || null;
}

function renderBar() {
  const state = UI.state;
  if (!state) return;

  const docGroup = $("doc-group");
  docGroup.innerHTML = "";
  state.documents.forEach((doc) => {
    const button = document.createElement("button");
    button.textContent = doc.label;
    button.className = doc.id === UI.docId ? "active" : "";
    button.onclick = () => selectDoc(doc.id);
    docGroup.appendChild(button);
  });

  const profileGroup = $("profile-group");
  profileGroup.innerHTML = "";
  const doc = currentDoc();
  (doc?.profiles || []).forEach((profile) => {
    const build = buildFor(doc.id, profile.name);
    const button = document.createElement("button");
    button.textContent = profile.name;
    button.className = profile.name === UI.profile ? "active" : "";
    button.title = build ? `${build.status}${build.message ? ": " + build.message : ""}` : "";
    button.onclick = () => selectProfile(profile.name);
    profileGroup.appendChild(button);
  });

  const recompile = $("recompile-group");
  recompile.innerHTML = "";
  const all = document.createElement("button");
  all.textContent = "recompile all";
  all.onclick = () => postJSON("/api/recompile", { target: "all", current: UI.docId });
  recompile.appendChild(all);
  state.documents.forEach((entry) => {
    const button = document.createElement("button");
    button.textContent = entry.label;
    button.title = `Recompile ${entry.label} only`;
    button.onclick = () => postJSON("/api/recompile", { target: entry.id, current: UI.docId });
    recompile.appendChild(button);
  });

  $("zoom-label").textContent = `${Math.round(UI.scale * 100)}%`;
  renderStatus();
  renderLogPaths();
}

function renderStatus(override) {
  const node = $("status");
  if (override) {
    node.textContent = override.text;
    node.className = `status ${override.cls || "busy"}`;
    return;
  }
  const build = buildFor(UI.docId, UI.profile);
  if (!build || build.status === "unknown") {
    // Build statuses are per-process, so after a restart a perfectly good PDF
    // from a previous session has no status attached. Say so, rather than
    // claiming "not built" while displaying it.
    const cached = build && build.has_pdf;
    node.textContent = cached ? "cached" : "not built";
    node.title = cached ? "Built in an earlier session; recompile to refresh." : "";
    node.className = "status";
    return;
  }
  const seconds = build.duration_s ? ` (${build.duration_s}s)` : "";
  node.textContent = build.status === "ok" ? `ok${seconds}` : `${build.status}${seconds}`;
  node.className = `status ${build.status}`;
  node.title = build.message || "";
}

function renderLogPaths() {
  const build = buildFor(UI.docId, UI.profile);
  $("log-paths").innerHTML = build
    ? `<div>latexmk: <code>${build.driver_log_path}</code></div>
       <div>TeX: <code>${build.tex_log_path}</code></div>
       <div>build: <code>${build.build_dir}</code></div>`
    : "";
}

async function selectDoc(docId) {
  UI.docId = docId;
  const doc = currentDoc();
  if (doc && !doc.profiles.some((p) => p.name === UI.profile)) {
    UI.profile = doc.active_profile || doc.profiles[0]?.name;
  }
  renderBar();
  await renderPdf(null);
  if (UI.logKind !== "live") loadLog(UI.logKind);
}

async function selectProfile(name) {
  if (name === UI.profile) return;
  // The whole point: keep the reader exactly where they were.
  const anchor = captureAnchor();
  UI.profile = name;
  postJSON(`/api/active-profile/${UI.docId}/${name}`).catch(() => {});
  renderBar();
  await renderPdf(anchor);
  if (UI.logKind !== "live") loadLog(UI.logKind);
}

/* ------------------------------------------------------------ log panel */

function appendLog(line) {
  UI.liveLines.push(line);
  if (UI.liveLines.length > 5000) UI.liveLines.splice(0, 1000);
  if (UI.logKind !== "live" || $("log-panel").hidden) return;
  const body = $("log-body");
  const atBottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 30;
  const span = document.createElement("span");
  span.textContent = line + "\n";
  if (/^\[cf_view\]/.test(line)) span.className = "log-meta";
  else if (/^!|error|Error|Emergency stop/.test(line)) span.className = "log-err";
  else if (/warning|Warning|undefined/i.test(line)) span.className = "log-warn";
  body.appendChild(span);
  if (atBottom) body.scrollTop = body.scrollHeight;
}

function showLive() {
  const body = $("log-body");
  body.textContent = "";
  UI.liveLines.forEach((line) => appendLogRaw(body, line));
  body.scrollTop = body.scrollHeight;
}

function appendLogRaw(body, line) {
  const span = document.createElement("span");
  span.textContent = line + "\n";
  if (/^\[cf_view\]/.test(line)) span.className = "log-meta";
  else if (/^!|Emergency stop/.test(line)) span.className = "log-err";
  else if (/warning|undefined/i.test(line)) span.className = "log-warn";
  body.appendChild(span);
}

async function loadLog(kind) {
  UI.logKind = kind;
  [...$("log-tabs").children].forEach((b) =>
    b.classList.toggle("active", b.dataset.kind === kind));
  if (kind === "live") { showLive(); return; }
  const body = $("log-body");
  body.textContent = "loading...";
  try {
    const response = await fetch(`/api/log/${UI.docId}/${UI.profile}?kind=${kind}&t=${Date.now()}`);
    const text = await response.text();
    body.textContent = "";
    text.split("\n").forEach((line) => appendLogRaw(body, line));
  } catch (error) {
    body.textContent = String(error);
  }
}

/* ------------------------------------------------------------ menu */

function renderMenu() {
  const state = UI.state;
  $("menu-config").innerHTML = `config: <code>${state.config_path}</code><br>
    compile command: <code>${state.latex_cmd}</code>`;

  const docs = $("menu-docs");
  docs.innerHTML = "";
  state.documents.forEach((doc) => {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `<b>${doc.label}</b> <span class="mono hint">${doc.main_tex}</span>`;
    const remove = document.createElement("button");
    remove.textContent = "remove";
    remove.onclick = async () => {
      if (!confirm(`Remove document "${doc.label}" from the session?`)) return;
      applyState(await api(`/api/documents/${doc.id}`, { method: "DELETE" }));
      renderMenu();
    };
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    row.append(spacer, remove);
    docs.appendChild(row);
  });

  const macros = $("menu-macros");
  macros.innerHTML = "";
  const first = state.documents[0];
  const clean = first?.profiles.find((p) => p.name === "clean");
  (clean?.transforms || []).forEach((transform) => {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `<span class="mono">${transformLabel(transform)}</span>
                     <span class="hint">${transform.mode}</span>`;
    const remove = document.createElement("button");
    remove.textContent = "remove";
    remove.onclick = () => updateMacros(
      (clean.transforms || []).filter((t) => transformId(t) !== transformId(transform)));
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    row.append(spacer, remove);
    macros.appendChild(row);
  });

  const hooks = $("menu-hooks");
  hooks.innerHTML = "";
  state.global_hooks.forEach((hook, index) => {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `<span class="mono">${hook.command}</span>`;
    const remove = document.createElement("button");
    remove.textContent = "remove";
    remove.onclick = async () => {
      applyState(await api(`/api/hooks/${index}`, { method: "DELETE" }));
      renderMenu();
    };
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    row.append(spacer, remove);
    hooks.appendChild(row);
  });
}

/* A macro and an environment can share a name and are stripped differently, so the
   identity of a transform is the pair -- the same rule the server reconciles on. */
function transformId(t) {
  return t.environment_name ? `env:${t.environment_name}` : `macro:${t.macro_name}`;
}

function transformLabel(t) {
  return t.environment_name
    ? `\\begin{${t.environment_name}}...\\end{${t.environment_name}}`
    : `\\${t.macro_name}{...}`;
}

async function updateMacros(transforms) {
  const payload = transforms.map((t) => ({
    macro_name: t.macro_name, environment_name: t.environment_name, mode: t.mode,
  }));
  for (const doc of UI.state.documents) {
    applyState(await api(`/api/documents/${doc.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clean_transforms: payload }),
    }));
  }
  renderMenu();
  renderBar();
}

/* ------------------------------------------------------------ wiring */

function applyState(state) {
  UI.state = state;
  if (!UI.docId || !state.documents.some((d) => d.id === UI.docId)) {
    UI.docId = state.documents[0]?.id || null;
    UI.profile = state.documents[0]?.active_profile || "full";
  }
  renderBar();
}

function connectEvents() {
  const source = new EventSource("/api/events");
  source.addEventListener("batch_started", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(`[cf_view] batch started: ${payload.queue.map((q) => q.doc_id).join(", ")}`);
    renderStatus({ text: "compiling...", cls: "busy" });
  });
  source.addEventListener("hook_started", (event) =>
    appendLog(`[cf_view] hook (${JSON.parse(event.data).scope}): ${JSON.parse(event.data).command}`));
  source.addEventListener("hook_finished", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(`[cf_view] hook exited ${payload.exit_code}`);
  });
  source.addEventListener("build_started", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(`[cf_view] building ${payload.doc_id}/${payload.profile}`);
  });
  source.addEventListener("log_line", (event) => appendLog(JSON.parse(event.data).line));
  source.addEventListener("build_finished", async (event) => {
    const payload = JSON.parse(event.data);
    appendLog(`[cf_view] ${payload.doc_id}/${payload.profile}: ${payload.status} `
              + `(${payload.duration_s}s)${payload.message ? " -- " + payload.message : ""}`);
    UI.state = await api("/api/state");
    renderBar();
    // Reload as soon as *this* build lands, without waiting for the batch.
    if (payload.doc_id === UI.docId && payload.profile === UI.profile) await reloadPdf();
  });
  source.addEventListener("batch_finished", (event) => {
    const payload = JSON.parse(event.data);
    appendLog(payload.ok ? "[cf_view] batch finished" :
              `[cf_view] batch finished with failures: ${payload.failed.join(", ")}`);
    renderStatus();
  });
}

function wireControls() {
  $("zoom-in").onclick = async () => {
    UI.scale = Math.min(3, UI.scale + 0.15); renderBar(); await reloadPdf(); };
  $("zoom-out").onclick = async () => {
    UI.scale = Math.max(0.3, UI.scale - 0.15); renderBar(); await reloadPdf(); };
  $("toggle-native").onclick = async () => {
    UI.native = !UI.native;
    $("toggle-native").classList.toggle("active", UI.native);
    // Zoom is the canvas renderer's; in native mode the browser owns it.
    for (const id of ["zoom-in", "zoom-out"]) $(id).disabled = UI.native;
    await renderPdf(UI.native ? null : captureAnchor());
  };

  $("toggle-log").onclick = () => {
    const panel = $("log-panel");
    panel.hidden = !panel.hidden;
    if (!panel.hidden) loadLog(UI.logKind);
  };
  [...$("log-tabs").children].forEach((button) => {
    button.onclick = () => loadLog(button.dataset.kind);
  });
  $("log-clear").onclick = () => { UI.liveLines = []; $("log-body").textContent = ""; };
  $("toggle-menu").onclick = () => { $("menu").hidden = false; renderMenu(); };
  $("menu-close").onclick = () => { $("menu").hidden = true; };

  $("new-doc-add").onclick = async () => {
    const label = $("new-doc-label").value.trim();
    const path = $("new-doc-path").value.trim();
    if (!label || !path) return;
    try {
      applyState(await postJSON("/api/documents", { label, main_tex: path }));
      $("new-doc-label").value = ""; $("new-doc-path").value = "";
      renderMenu();
    } catch (error) { alert(error.message); }
  };
  $("new-macro-add").onclick = async () => {
    const name = $("new-macro-name").value.trim().replace(/^\\/, "");
    if (!name) return;
    const clean = UI.state.documents[0]?.profiles.find((p) => p.name === "clean");
    const entry = $("new-macro-kind").value === "environment"
      ? { environment_name: name, mode: $("new-macro-mode").value }
      : { macro_name: name, mode: $("new-macro-mode").value };
    const next = [...(clean?.transforms || []), entry];
    await updateMacros(next);
    $("new-macro-name").value = "";
  };
  $("new-hook-add").onclick = async () => {
    const command = $("new-hook-cmd").value.trim();
    if (!command) return;
    applyState(await postJSON("/api/hooks", { command }));
    $("new-hook-cmd").value = "";
    renderMenu();
  };

  document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
    const doc = currentDoc();
    if (event.key === "c" && doc) {
      const names = doc.profiles.map((p) => p.name);
      selectProfile(names[(names.indexOf(UI.profile) + 1) % names.length]);
    }
    if (event.key === "r") postJSON("/api/recompile", { target: "all", current: UI.docId });
    if (event.key === "l") $("toggle-log").click();
    if (event.key === "t") $("toggle-native").click();
  });
}

(async function start() {
  wireControls();
  applyState(await api("/api/state"));
  connectEvents();
  await renderPdf(null);
})();
