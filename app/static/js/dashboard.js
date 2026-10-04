/* Isnad database — admin dashboard.
 * Authentication is the HttpOnly session cookie set at login; no keys live in this file. */

const API = "/api";
const CURRENT_ADMIN_ID = Number(document.currentScript.dataset.adminId);
const IS_OWNER = document.currentScript.dataset.isOwner === "true";

const $ = (id) => document.getElementById(id);

const KIND_LABELS = { document: "مستند", structured_hadith: "أحاديث منظّمة" };
const TABS = {
  status: { title: "الحالة", subtitle: "نظرة عامة على قاعدة البيانات وصحة الأنظمة" },
  sources: { title: "المصادر", subtitle: "رفع الكتب والأحاديث المعتمدة ومتابعة معالجتها" },
  control: { title: "التحكم بالموقع", subtitle: "إعدادات الموقع الأساسي وطريقة ربطه بقاعدة البيانات" },
  reports: { title: "الإحصائيات والتقارير", subtitle: "زوار الموقع وعمليات البحث والأسئلة، مع التصدير" },
  admins: { title: "المستخدمون", subtitle: "حسابك والمستخدمون المصرّح لهم بالدخول" },
};

// ---------- helpers ----------

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, options);
  if (res.status === 401) {
    window.location.href = "/login"; // session expired
    throw new Error("انتهت الجلسة");
  }
  if (!res.ok) {
    let detail = `خطأ (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function icon(name, cls = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function alertBox(id, text, kind = "ok") {
  const node = $(id);
  node.textContent = text;
  node.className = `alert ${kind}`;
  node.hidden = !text;
}

function toast(message, kind = "ok") {
  const item = el("div", undefined, `toast ${kind}`);
  item.append(icon(kind === "error" ? "alert" : "check"), el("span", message));
  $("toasts").append(item);
  setTimeout(() => item.remove(), 3500);
}

const numberFmt = new Intl.NumberFormat("ar-SA-u-nu-latn");
const fmt = (n) => (n === null || n === undefined ? "—" : numberFmt.format(n));

function formatDate(utc) {
  // The server stores "YYYY-MM-DD HH:MM:SS" in UTC; show it in the browser's time zone.
  const d = new Date(utc.replace(" ", "T") + "Z");
  return isNaN(d) ? utc : d.toLocaleString("ar-SA-u-nu-latn", { dateStyle: "medium", timeStyle: "short" });
}

function formatSize(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function tiles(containerId, items) {
  const box = $(containerId);
  box.replaceChildren();
  for (const [iconName, label, value] of items) {
    const tile = el("div", undefined, "tile");
    const iconBox = el("span", undefined, "tile-icon");
    iconBox.append(icon(iconName));
    const body = el("div", undefined, "tile-body");
    body.append(el("span", fmt(value), "tile-value"), el("span", label, "tile-label"));
    tile.append(iconBox, body);
    box.append(tile);
  }
}

function skeletonTiles(containerId, count) {
  $(containerId).replaceChildren(...Array.from({ length: count }, () => el("div", undefined, "tile skeleton")));
}

function setupPasswordToggles() {
  document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = $(btn.dataset.togglePassword);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      const label = show ? "إخفاء كلمة المرور" : "إظهار كلمة المرور";
      btn.setAttribute("aria-label", label);
      btn.title = label;
      btn.classList.toggle("active", show);
    });
  });
}

// ---------- tabs ----------

const loaded = new Set();
const LOADERS = {};

function showTab(name) {
  if (!TABS[name]) name = "status";
  for (const tab of Object.keys(TABS)) {
    $(`tab-${tab}`).hidden = tab !== name;
    document.querySelector(`[data-tab="${tab}"]`).setAttribute("aria-selected", tab === name);
  }
  $("page-title").textContent = TABS[name].title;
  $("page-subtitle").textContent = TABS[name].subtitle;
  document.title = `${TABS[name].title} — إسناد`;
  if (!loaded.has(name)) {
    loaded.add(name);
    LOADERS[name]();
  }
}

// ---------- status ----------

const CHECK_ICONS = [
  ["قاعدة بيانات التطبيق", "database"],
  ["المتجهية", "layers"],
  ["التمثيلات", "sparkle"],
  ["OCR", "scan"],
  ["التخزين", "disk"],
  ["SITE_API_KEY", "key"],
  ["OpenRouter", "key"],
  ["الموقع الأساسي", "globe"],
];
const STATE = {
  ok: { label: "يعمل", icon: "check" },
  fail: { label: "يحتاج انتباه", icon: "x" },
  unset: { label: "غير مضبوط", icon: "minus" },
};

async function loadOverview() {
  skeletonTiles("overview-tiles", 6);
  try {
    const s = await api("/reports/summary");
    tiles("overview-tiles", [
      ["eye", "زيارة", s.visits],
      ["user", "زائر", s.unique_visitors],
      ["search", "عملية بحث", s.searches],
      ["message", "سؤال حوار", s.chats],
      ["files", "ملف في القاعدة", s.files],
      ["layers", "مقطع مفهرس", s.chunks],
    ]);
  } catch (err) {
    $("overview-tiles").replaceChildren(el("p", err.message, "alert error"));
  }
}

async function loadStatus() {
  loadOverview();
  const list = $("status-list");
  $("status-btn").disabled = true;
  list.replaceChildren(...Array.from({ length: 6 }, () => el("li", undefined, "check skeleton")));
  try {
    const status = await api("/status");
    list.replaceChildren();
    let failing = 0;
    for (const check of status.checks) {
      const state = check.ok === true ? "ok" : check.ok === false ? "fail" : "unset";
      if (state === "fail") failing++;
      const li = el("li", undefined, `check ${state}`);
      const iconBox = el("span", undefined, "check-icon");
      iconBox.append(icon((CHECK_ICONS.find(([key]) => check.name.includes(key)) || [, "activity"])[1]));
      const body = el("div", undefined, "check-body");
      body.append(el("span", check.name, "check-name"), el("span", check.detail, "check-detail"));
      if (check.latency_ms !== null) body.append(el("span", `${check.latency_ms} ms`, "check-time"));
      const badge = el("span", undefined, "check-state");
      badge.append(icon(STATE[state].icon), document.createTextNode(STATE[state].label));
      li.append(iconBox, body, badge);
      list.append(li);
    }
    const summary = $("status-summary");
    summary.replaceChildren(
      icon(failing ? "alert" : "check", "icon xs"),
      document.createTextNode(failing ? `${failing} تحتاج انتباه` : "كل الأنظمة المضبوطة تعمل"),
    );
    summary.className = `pill ${failing ? "fail" : "ok"}`;
    summary.hidden = false;
    $("status-time").textContent = `آخر فحص: ${formatDate(status.checked_at.replace(" UTC", ""))}`;
  } catch (err) {
    list.replaceChildren(el("li", err.message, "alert error"));
  } finally {
    $("status-btn").disabled = false;
  }
}
LOADERS.status = loadStatus;

// ---------- sources ----------

let allSources = [];
let pollTimer = null;
const POLL_MS = 3000;
const IMAGE_EXT = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"];

function fileBadge(filename) {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  const isImage = IMAGE_EXT.includes(ext);
  return el("span", isImage ? "IMG" : ext.toUpperCase().slice(0, 4), `file-badge ${isImage ? "img" : ext}`);
}

function progressBar(ratio) {
  const bar = el("div", undefined, ratio === null ? "progress indeterminate" : "progress");
  const fill = el("span");
  if (ratio !== null) fill.style.width = `${Math.round(ratio * 100)}%`;
  bar.append(fill);
  return bar;
}

function progressRatio(text) {
  // Progress lines look like "قراءة الصفحات 45/300" or "إنشاء التمثيلات الدلالية 640/1213".
  const match = /(\d+)\s*\/\s*(\d+)/.exec(text || "");
  return match && Number(match[2]) ? Number(match[1]) / Number(match[2]) : null;
}

// XMLHttpRequest instead of fetch: it reports upload progress, which matters for 60 MB books.
function sendFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/sources`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status === 401) {
        window.location.href = "/login";
        return reject(new Error("انتهت الجلسة"));
      }
      let body = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body);
      const detail = typeof body.detail === "string" ? body.detail : `خطأ (${xhr.status})`;
      reject(new Error(xhr.status === 413 && !body.detail ? "حجم الملف أكبر من المسموح" : detail));
    };
    xhr.onerror = () => reject(new Error("انقطع الاتصال أثناء الرفع"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

function uploadItem(file) {
  const li = el("li", undefined, "upload-item");
  const body = el("div", undefined, "upload-body");
  const note = el("span", `جارٍ الرفع — ${formatSize(file.size)}`, "upload-note");
  const bar = progressBar(0);
  body.append(el("span", file.name, "upload-name"), bar, note);
  li.append(fileBadge(file.name), body);
  $("upload-log").prepend(li);
  return {
    progress(ratio) {
      bar.firstChild.style.width = `${Math.round(ratio * 100)}%`;
      note.textContent = `جارٍ الرفع ${Math.round(ratio * 100)}% — ${formatSize(file.size)}`;
    },
    done(text, kind) {
      bar.remove();
      note.textContent = text;
      li.classList.add(kind);
      if (kind === "ok") setTimeout(() => li.remove(), 8000);
    },
  };
}

async function uploadFiles(files) {
  if (!files.length) return;
  $("files").disabled = true;
  // Uploaded one after another; the server then indexes them in the background, in order.
  for (const file of files) {
    const item = uploadItem(file);
    try {
      const data = await sendFile(file, (ratio) => item.progress(ratio));
      item.done("✓ استُلم — تجري معالجته في الخلفية، تابع حالته في الجدول", "ok");
      toast(`استُلم ${data.filename}`);
    } catch (err) {
      item.done(err.message, "error");
    }
    loadSources();
  }
  $("files").disabled = false;
  $("files").value = "";
}

function statusCell(s) {
  const td = el("td", undefined, `status-cell ${s.status}`);
  if (s.status === "processing") {
    const badge = el("span", undefined, "badge processing");
    badge.append(icon("clock"), document.createTextNode("قيد المعالجة"));
    td.append(badge, progressBar(progressRatio(s.progress)), el("span", s.progress || "", "status-note"));
  } else if (s.status === "failed") {
    const badge = el("span", undefined, "badge failed");
    badge.append(icon("x"), document.createTextNode("فشل"));
    td.append(badge, el("span", s.error || "", "status-note"));
  } else {
    const badge = el("span", undefined, "badge ready");
    badge.append(icon("check"), document.createTextNode("جاهز"));
    td.append(badge);
    if (s.error) td.append(el("span", s.error, "status-note warn"));
  }
  return td;
}

function renderSources() {
  const filter = $("sources-filter").value.trim().toLowerCase();
  const rows = allSources.filter((s) => s.filename.toLowerCase().includes(filter));
  const body = $("sources-body");
  body.replaceChildren();
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", allSources.length ? "لا توجد ملفات بهذا الاسم" : "لم تُرفع أي ملفات بعد — ابدأ برفع مصادركم المعتمدة", "empty");
    td.colSpan = 6;
    tr.append(td);
    body.append(tr);
    return;
  }
  for (const s of rows) {
    const tr = el("tr");
    const processing = s.status === "processing";

    const fileTd = el("td");
    const cell = el("div", undefined, "file-cell");
    const text = el("div", undefined, "file-text");
    const meta = [KIND_LABELS[s.kind] || s.kind, formatSize(s.size_bytes)];
    if (s.ocr_pages) meta.push(`${fmt(s.ocr_pages)} صفحة OCR`);
    text.append(el("span", s.filename, "file-name"), el("span", meta.join(" · "), "file-meta"));
    cell.append(fileBadge(s.filename), text);
    fileTd.append(cell);

    // data-label: the column name shown above each value when the table becomes cards on phones
    const labelled = (label, text, cls) => {
      const td = el("td", text, cls);
      td.dataset.label = label;
      return td;
    };
    tr.append(
      fileTd,
      statusCell(s),
      labelled("المقاطع", processing && !s.chunks ? "—" : fmt(s.chunks), "num"),
      labelled("رفعه", s.uploaded_by || "—"),
      labelled("تاريخ الرفع", formatDate(s.uploaded_at)),
    );

    const actions = el("td", undefined, "actions");
    if (s.status !== "failed" && !(processing && !s.chunks)) {
      const download = el("a", undefined, "icon-btn");
      download.href = `${API}/sources/${s.id}/download`;
      download.title = "تنزيل الملف الأصلي";
      download.setAttribute("aria-label", `تنزيل ${s.filename}`);
      download.append(icon("download"));
      actions.append(download);
    }
    if (!processing) {
      const del = el("button", undefined, "icon-btn danger");
      del.type = "button";
      del.title = "حذف";
      del.setAttribute("aria-label", `حذف ${s.filename}`);
      del.append(icon("trash"));
      del.addEventListener("click", () => deleteSource(s));
      actions.append(del);
    }
    tr.append(actions);
    body.append(tr);
  }
}

async function loadSources() {
  try {
    const data = await api("/sources");
    allSources = data.sources;
    const busy = allSources.filter((s) => s.status === "processing").length;
    $("sources-summary").textContent =
      `${fmt(data.total_files)} ملف جاهز · ${fmt(data.total_chunks)} مقطع مفهرس` +
      (busy ? ` · ${fmt(busy)} قيد المعالجة` : "");
    $("nav-busy").textContent = fmt(busy);
    $("nav-busy").hidden = !busy;
    renderSources();
    // Keep refreshing while anything is being processed.
    clearTimeout(pollTimer);
    if (busy) pollTimer = setTimeout(loadSources, POLL_MS);
  } catch (err) {
    $("sources-summary").textContent = `تعذّر جلب الملفات: ${err.message}`;
  }
}
LOADERS.sources = loadSources;

async function deleteSource(source) {
  if (!confirm(`حذف "${source.filename}" من قاعدة البيانات نهائيًا؟\nسيُحذف من نتائج البحث ويُحذف الملف الأصلي.`)) return;
  try {
    await api(`/sources/${source.id}`, { method: "DELETE" });
    toast(`حُذف ${source.filename}`);
  } catch (err) {
    toast(err.message, "error");
  }
  loadSources();
}

// ---------- website control ----------

const CONTROL_FIELDS = ["maintenance_mode", "maintenance_message", "search_enabled", "chat_enabled", "announcement", "main_site_url"];
let savedControl = "";

function readControl() {
  const payload = {};
  for (const field of CONTROL_FIELDS) {
    const input = $(field);
    payload[field] = input.type === "checkbox" ? input.checked : input.value.trim();
  }
  return payload;
}

function onControlChange() {
  const dirty = JSON.stringify(readControl()) !== savedControl;
  $("control-save").disabled = !dirty;
  $("control-dirty").hidden = !dirty;
  $("maintenance-message-row").classList.toggle("disabled", !$("maintenance_mode").checked);
}

async function loadControl() {
  document.querySelectorAll(".endpoint").forEach((n) => (n.textContent = `${location.origin}/api/v1${n.dataset.path}`));
  try {
    const settings = await api("/site-settings");
    for (const field of CONTROL_FIELDS) {
      const input = $(field);
      if (input.type === "checkbox") input.checked = settings[field];
      else input.value = settings[field];
    }
    savedControl = JSON.stringify(readControl());
    onControlChange();
  } catch (err) {
    alertBox("control-message", err.message, "error");
  }
}
LOADERS.control = loadControl;

async function saveControl(event) {
  event.preventDefault();
  const payload = readControl();
  $("control-save").disabled = true;
  try {
    await api("/site-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    savedControl = JSON.stringify(payload);
    $("control-message").hidden = true;
    toast("حُفظت إعدادات الموقع");
  } catch (err) {
    alertBox("control-message", err.message, "error");
  }
  onControlChange();
}

async function copyEndpoint(btn) {
  const text = btn.parentElement.querySelector(".endpoint").textContent;
  try {
    await navigator.clipboard.writeText(text);
    btn.classList.add("done");
    btn.replaceChildren(icon("check"));
    setTimeout(() => {
      btn.classList.remove("done");
      btn.replaceChildren(icon("copy"));
    }, 1500);
  } catch {
    toast("تعذّر النسخ — انسخ الرابط يدويًا", "error");
  }
}

// ---------- reports ----------

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function setRange(days) {
  const today = new Date();
  $("report-to").value = isoDate(today);
  $("report-from").value = isoDate(new Date(today.getTime() - (days - 1) * 86400000));
  document.querySelectorAll(".presets .chip").forEach((c) => c.setAttribute("aria-pressed", Number(c.dataset.days) === days));
}

function reportQuery() {
  return `from=${$("report-from").value}&to=${$("report-to").value}`;
}

function rankList(id, items, emptyText = "لا توجد بيانات في هذه الفترة") {
  const list = $(id);
  list.replaceChildren();
  if (!items.length) {
    list.append(el("li", emptyText, "empty"));
    return;
  }
  const max = Math.max(...items.map((i) => i.count));
  for (const item of items) {
    const li = el("li");
    const bar = el("span", undefined, "rank-bar");
    bar.style.inlineSize = `${(item.count / max) * 100}%`;
    li.append(bar, el("span", item.label, "rank-label"), el("span", fmt(item.count), "rank-count"));
    list.append(li);
  }
}

function niceMax(value) {
  // A round, even axis maximum so the midpoint tick is a whole number too.
  if (value <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 2, 4, 5, 10]) {
    const candidate = factor * magnitude;
    if (candidate >= value && candidate % 2 === 0) return candidate;
  }
  return 10 * magnitude;
}

function showTooltip(target, day) {
  const tip = $("chart-tooltip");
  tip.replaceChildren(el("div", day.day, "tt-title"));
  for (const [label, value, main] of [
    ["الزيارات", day.visits, true],
    ["الزوار", day.visitors],
    ["عمليات البحث", day.searches],
    ["أسئلة الحوار", day.chats],
  ]) {
    const row = el("div", undefined, `tt-row${main ? " main" : ""}`);
    row.append(el("span", label), el("strong", fmt(value)));
    tip.append(row);
  }
  tip.hidden = false;
  const rect = target.getBoundingClientRect();
  const width = tip.offsetWidth;
  const left = Math.min(window.innerWidth - width - 8, Math.max(8, rect.left + rect.width / 2 - width / 2));
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(8, rect.top - tip.offsetHeight - 8)}px`;
}

function hideTooltip() {
  $("chart-tooltip").hidden = true;
}

let lastDaily = null;

function dailyChart(days) {
  lastDaily = days;
  const chart = $("daily-chart");
  chart.replaceChildren();
  const peak = Math.max(0, ...days.map((d) => d.visits));
  const total = days.reduce((sum, d) => sum + d.visits, 0);
  $("chart-caption").textContent = total
    ? `${fmt(total)} زيارة خلال ${fmt(days.length)} يومًا · أعلى يوم ${fmt(peak)}`
    : `لا زيارات خلال ${fmt(days.length)} يومًا`;

  const max = niceMax(peak);
  const axis = el("div", undefined, "chart-axis");
  axis.append(el("span", fmt(max)), el("span", fmt(max / 2)), el("span", "0"));

  const plot = el("div", undefined, "chart-plot");
  const grid = el("div", undefined, "chart-grid");
  grid.append(el("span"), el("span"), el("span"));
  const bars = el("div", undefined, "chart-bars");
  const labels = el("div", undefined, "chart-labels");
  // Enough room for a "MM-DD" label every ~48px, whatever the screen width.
  const room = Math.max(3, Math.floor((chart.clientWidth || 600) / 48));
  const every = Math.ceil(days.length / room);

  days.forEach((d, i) => {
    const slot = el("div", undefined, "bar-slot");
    slot.tabIndex = 0;
    slot.setAttribute("aria-label", `${d.day}: ${d.visits} زيارة`);
    const bar = el("div", undefined, d.visits ? "bar" : "bar zero");
    bar.style.height = `${(d.visits / max) * 100}%`;
    slot.append(bar);
    for (const evt of ["pointerenter", "focus"]) slot.addEventListener(evt, () => showTooltip(slot, d));
    for (const evt of ["pointerleave", "blur"]) slot.addEventListener(evt, hideTooltip);
    bars.append(slot);
    labels.append(el("span", i % every === 0 ? d.day.slice(5) : ""));
  });

  plot.append(grid, bars, labels);
  chart.append(axis, plot);

  // The same numbers as a table: nothing in the chart is reachable only by hovering.
  const table = el("table", undefined, "data-table");
  const head = el("tr");
  for (const h of ["اليوم", "الزيارات", "الزوار", "البحث", "الحوار"]) head.append(el("th", h));
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const d of [...days].reverse()) {
    const tr = el("tr");
    tr.append(el("td", d.day), el("td", fmt(d.visits), "num"), el("td", fmt(d.visitors), "num"), el("td", fmt(d.searches), "num"), el("td", fmt(d.chats), "num"));
    tbody.append(tr);
  }
  table.append(thead, tbody);
  $("daily-table").replaceChildren(table);
}

async function loadReport() {
  $("report-message").hidden = true;
  $("export-xlsx").href = `${API}/reports/export?format=xlsx&${reportQuery()}`;
  $("export-pdf").href = `${API}/reports/export?format=pdf&${reportQuery()}`;
  skeletonTiles("report-tiles", 6);
  try {
    const s = await api(`/reports/summary?${reportQuery()}`);
    tiles("report-tiles", [
      ["eye", "زيارة", s.visits],
      ["user", "زائر فريد", s.unique_visitors],
      ["search", "عملية بحث", s.searches],
      ["message", "سؤال حوار", s.chats],
      ["clock", "متوسط زمن البحث (ms)", s.avg_search_latency_ms],
      ["upload", "ملف رُفع في الفترة", s.uploads_in_period],
    ]);
    dailyChart(s.daily);
    rankList("top-searches", s.top_searches);
    rankList("top-questions", s.top_questions);
    rankList("search-results", s.search_results);
  } catch (err) {
    $("report-tiles").replaceChildren();
    alertBox("report-message", err.message, "error");
  }
}
LOADERS.reports = loadReport;

// ---------- users ----------

async function loadAdmins() {
  try {
    const admins = await api("/admins");
    const list = $("admins-list");
    list.replaceChildren();
    for (const admin of admins) {
      const li = el("li", undefined, "person");
      const text = el("div", undefined, "person-text");
      text.append(el("strong", admin.username), el("span", admin.created_at ? `أُضيف ${formatDate(admin.created_at)}` : "", "muted small"));
      const tags = el("div", undefined, "person-tags");
      if (admin.is_owner) tags.append(el("span", "مدير النظام", "tag you"));
      if (admin.id === CURRENT_ADMIN_ID) tags.append(el("span", "أنت", "tag you"));
      if (admin.must_change_password) tags.append(el("span", "كلمة مرور افتراضية", "tag weak"));
      text.append(tags);
      li.append(el("span", admin.username.slice(0, 1).toUpperCase(), "avatar"), text);
      if (IS_OWNER && !admin.is_owner && admin.id !== CURRENT_ADMIN_ID) {
        const del = el("button", undefined, "icon-btn danger");
        del.type = "button";
        del.title = "حذف المستخدم";
        del.setAttribute("aria-label", `حذف ${admin.username}`);
        del.append(icon("trash"));
        del.addEventListener("click", () => deleteAdmin(admin));
        li.append(del);
      }
      list.append(li);
    }
  } catch (err) {
    alertBox("admin-message", err.message, "error");
  }
}
LOADERS.admins = loadAdmins;

async function addAdmin(event) {
  event.preventDefault();
  try {
    const admin = await api("/admins", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("new-username").value.trim(), password: $("new-password").value }),
    });
    $("admin-form").reset();
    $("admin-message").hidden = true;
    toast(`أُضيف المستخدم ${admin.username}`);
    loadAdmins();
  } catch (err) {
    alertBox("admin-message", err.message, "error");
  }
}

async function deleteAdmin(admin) {
  if (!confirm(`حذف المستخدم "${admin.username}"؟ لن يتمكن من الدخول بعد ذلك.`)) return;
  try {
    await api(`/admins/${admin.id}`, { method: "DELETE" });
    toast(`حُذف ${admin.username}`);
  } catch (err) {
    toast(err.message, "error");
  }
  loadAdmins();
}

function passwordStrength(value) {
  if (!value) return { score: 0, text: "8 أحرف على الأقل", color: "transparent" };
  if (value.length < 8) return { score: 1, text: `قصيرة — ${8 - value.length} أحرف أخرى على الأقل`, color: "var(--danger)" };
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(value)).length;
  if (value.length >= 12 && variety >= 3) return { score: 4, text: "قوية", color: "var(--ok)" };
  if (value.length >= 10 || variety >= 3) return { score: 3, text: "جيدة", color: "var(--chart-series)" };
  return { score: 2, text: "مقبولة — أضف أرقامًا أو رموزًا لتقويتها", color: "#C98A00" };
}

function onNewPasswordInput() {
  const { score, text, color } = passwordStrength($("new-own-password").value);
  $("strength-bar").style.width = `${score * 25}%`;
  $("strength-bar").style.background = color;
  $("strength-text").textContent = text;
}

async function changeOwnPassword(event) {
  event.preventDefault();
  const next = $("new-own-password").value;
  if (next.length < 8) {
    alertBox("password-message", "كلمة المرور الجديدة يجب ألا تقل عن 8 أحرف", "error");
    return;
  }
  if (next !== $("confirm-own-password").value) {
    alertBox("password-message", "كلمتا المرور الجديدتان غير متطابقتين", "error");
    return;
  }
  try {
    await api("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("current-password").value, new_password: next }),
    });
    if ($("password-banner")) {
      // The other sections were locked until now: open the dashboard afresh.
      location.hash = "status";
      location.reload();
      return;
    }
    $("password-form").reset();
    onNewPasswordInput();
    $("password-message").hidden = true;
    toast("تم تغيير كلمة المرور");
    loadAdmins();
  } catch (err) {
    alertBox("password-message", err.message, "error");
  }
}

// ---------- startup ----------

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-tab]").forEach((btn) =>
    btn.addEventListener("click", () => {
      location.hash = btn.dataset.tab; // triggers hashchange → showTab
    }),
  );

  $("logout-btn").addEventListener("click", async () => {
    await fetch(`${API}/auth/logout`, { method: "POST" });
    window.location.href = "/login";
  });

  $("status-btn").addEventListener("click", loadStatus);

  $("files").addEventListener("change", () => uploadFiles(Array.from($("files").files)));
  const drop = $("drop-zone");
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("dragging");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("dragging"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("dragging");
    uploadFiles(Array.from(e.dataTransfer.files));
  });
  $("sources-filter").addEventListener("input", renderSources);

  $("control-form").addEventListener("submit", saveControl);
  $("control-form").addEventListener("input", onControlChange);
  $("control-form").addEventListener("change", onControlChange);
  document.querySelectorAll(".copy-btn").forEach((btn) => btn.addEventListener("click", () => copyEndpoint(btn)));

  setRange(30);
  document.querySelectorAll(".presets .chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      setRange(Number(chip.dataset.days));
      loadReport();
    }),
  );
  for (const id of ["report-from", "report-to"]) {
    $(id).addEventListener("change", () =>
      document.querySelectorAll(".presets .chip").forEach((c) => c.setAttribute("aria-pressed", "false")),
    );
  }
  $("report-btn").addEventListener("click", loadReport);
  $("chart-table-toggle").addEventListener("click", () => {
    const showTable = $("daily-table").hidden;
    $("daily-table").hidden = !showTable;
    $("daily-chart").hidden = showTable;
    $("chart-table-toggle").setAttribute("aria-pressed", showTable);
    $("chart-table-toggle").querySelector("span").textContent = showTable ? "عرض كمخطط" : "عرض كجدول";
  });
  window.addEventListener("scroll", hideTooltip, { passive: true });
  // Re-space the chart's date labels when the screen is resized or rotated.
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => lastDaily && dailyChart(lastDaily), 200);
  });

  $("admin-form")?.addEventListener("submit", addAdmin);
  $("password-form").addEventListener("submit", changeOwnPassword);
  $("new-own-password").addEventListener("input", onNewPasswordInput);
  setupPasswordToggles();

  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  // With the default password, only the password form works: start there.
  if ($("password-banner")) location.hash = "admins";
  showTab(location.hash.slice(1));
});
