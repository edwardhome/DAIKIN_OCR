"use strict";
const root = document.querySelector("#app");
let config,
  dirty = false,
  reviewMs = 0,
  activeSince = performance.now();
let jobView = 0;
let stopRecognition = () => {};
let disposeShare = () => {};
const componentLoads = new Map();

function loadComponent(name) {
  if (!componentLoads.has(name)) {
    componentLoads.set(
      name,
      new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = `/static/js/${name}.js`;
        script.onload = resolve;
        script.onerror = () => {
          componentLoads.delete(name);
          script.remove();
          reject(new Error("頁面元件載入失敗，請重新整理後再試。"));
        };
        document.head.append(script);
      }),
    );
  }
  return componentLoads.get(name);
}
const labels = {
  QUEUED: "等待辨識",
  PREPROCESSING: "處理照片",
  RUNNING: "辨識中",
  SUCCEEDED: "待人工確認",
  FAILED: "辨識失敗",
};
const correctionLabels = {
  OCR_ERROR: "OCR 誤讀",
  VLM_EXTRACTION_ERROR: "VLM 擷取錯誤",
  FIELD_MAPPING_ERROR: "欄位配對錯誤",
  UNIT_ERROR: "單位錯誤",
  FORMAT_ERROR: "格式錯誤",
  HALLUCINATION: "無影像依據",
  MISSING_VALUE: "漏填",
  WRONG_CANDIDATE: "選錯候選值",
  IMAGE_UNREADABLE: "照片無法辨讀",
  UNKNOWN: "原因未確定",
};
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined && text !== null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function add(parent, ...children) {
  children.filter(Boolean).forEach((c) => parent.append(c));
  return parent;
}
function button(text, fn, cls) {
  const n = el("button", text, cls);
  n.type = "button";
  n.addEventListener("click", fn);
  return n;
}
function link(text, href, cls) {
  const n = el("a", text, cls);
  n.href = href;
  return n;
}
function input(type, value = "") {
  const n = el("input");
  n.type = type;
  n.value = value;
  return n;
}
function select(options, value) {
  const n = el("select");
  options.forEach(([v, t]) => {
    const o = el("option", t);
    o.value = v;
    n.append(o);
  });
  if (value !== undefined) n.value = value;
  return n;
}
function labeled(text, n) {
  const l = el("label", text);
  l.append(n);
  return l;
}
function panel(title) {
  const n = el("section", null, "panel");
  if (title) n.append(el("h2", title));
  return n;
}
function notice(message, error = false) {
  const n = document.querySelector("#notice");
  n.textContent = message;
  n.className = error ? "error" : "";
  n.hidden = false;
}
function guarded(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (e) {
      notice(e.message, true);
    }
  };
}
async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.method && options.method !== "GET")
    headers["X-CSRF-Token"] =
      config?.csrf_token ||
      document.querySelector('meta[name="csrf-token"]').content;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("服務回覆無法讀取，請稍後再試。");
  }
  if (!response.ok) {
    if (response.status === 401) location.href = "/login";
    throw new Error(data.error?.message || "操作失敗。");
  }
  return data;
}
function rate(v) {
  return v?.rate === null || v?.rate === undefined
    ? "尚無資料"
    : `${(v.rate * 100).toFixed(1)}% (${v.numerator}/${v.denominator})`;
}
function seconds(ms) {
  return ms === null || ms === undefined ? "—" : `${(ms / 1000).toFixed(1)} 秒`;
}
function date(value) {
  return new Date(value).toLocaleString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour12: false,
  });
}
function table(headers, rows) {
  const wrap = el("div", null, "table-wrap"),
    t = el("table"),
    head = el("tr");
  headers.forEach((h) => head.append(el("th", h)));
  t.append(add(el("thead"), head));
  const body = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    row.forEach((v) => {
      const td = el("td");
      td.append(
        v instanceof Node ? v : document.createTextNode(String(v ?? "—")),
      );
      tr.append(td);
    });
    body.append(tr);
  });
  t.append(body);
  wrap.append(t);
  return wrap;
}
function jsonDetails(title, value) {
  const d = el("details");
  add(d, el("summary", title), el("pre", JSON.stringify(value, null, 2)));
  return d;
}
function profileSelect() {
  return select(
    config.profiles.map((p) => [
      p.id,
      `${p.provider} · ${p.model || "尚未設定模型"}`,
    ]),
    config.default_profile,
  );
}
function trackDirty() {
  dirty = true;
  document.querySelector("#share-panel")?.setAttribute("hidden", "");
  const hint = document.querySelector("#confirmation-hint");
  if (hint) hint.textContent = "內容已修改，請再次確認並儲存後分享。";
}
function accrue() {
  if (!document.hidden) reviewMs += performance.now() - activeSince;
  activeSince = performance.now();
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) reviewMs += performance.now() - activeSince;
  activeSince = performance.now();
});
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
window.addEventListener("pagehide", () => {
  jobView += 1;
  stopRecognition();
});
window.addEventListener("pageshow", (e) => {
  if (e.persisted && !dirty && location.pathname.startsWith("/jobs/"))
    guarded(() => jobPage(location.pathname.split("/")[2]))();
});

function home() {
  root.replaceChildren();
  const box = panel();
  box.classList.add("hero");
  add(
    box,
    el("p", "拍照 → AI 辨識 → 人工確認 → 分享", "eyebrow"),
    el("h1", "大金空調銘牌辨識"),
    el(
      "p",
      "盡量讓銘牌文字清楚入鏡。辨識後可對照照片，修改每個欄位。",
      "muted",
    ),
  );
  const profile = profileSelect();
  box.append(labeled("辨識模型", profile));
  if (config.profiles.every((p) => !p.configured))
    box.append(
      el(
        "p",
        "視覺模型尚未設定。請先完成伺服器的模型設定；照片仍可上傳與人工填寫。",
        "warning",
      ),
    );
  const difficulty = select([
    ["UNLABELED", "尚未標記"],
    ["EASY", "EASY · 正面清楚"],
    ["MEDIUM", "MEDIUM · 輕微斜拍／反光"],
    ["HARD", "HARD · 遠距離／龜裂／遮擋"],
  ]);
  const group = input("text");
  group.placeholder = "同一設備請使用相同代號（選填）";
  const scope = select([
    ["PRODUCTION", "現場辨識"],
    ["BENCHMARK_SOURCE", "Benchmark 樣本"],
  ]);
  const detail = el("details");
  add(
    detail,
    el("summary", "照片標記（選填）"),
    labeled("照片難度", difficulty),
    labeled("設備群組", group),
    labeled("用途", scope),
  );
  box.append(detail);
  const actions = el("div", null, "actions");
  function chooser(camera) {
    const file = input("file");
    file.accept = "image/jpeg,image/png,image/heic,image/heif,.heic,.heif";
    if (camera) file.setAttribute("capture", "environment");
    file.hidden = true;
    file.addEventListener(
      "change",
      guarded(async () => {
        const image = file.files[0];
        if (!image) return;
        if (image.size > config.max_upload_bytes)
          throw new Error("照片超過 20 MB 上傳限制。");
        actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
        notice("照片上傳中…");
        try {
          const data = new FormData();
          data.append("image", image);
          data.append("profile_id", profile.value);
          data.append("image_difficulty", difficulty.value);
          data.append("group_key", group.value);
          data.append("scope", scope.value);
          const result = await api("/api/jobs", { method: "POST", body: data });
          location.href = `/jobs/${result.id}`;
        } finally {
          actions
            .querySelectorAll("button")
            .forEach((b) => (b.disabled = false));
        }
      }),
    );
    box.append(file);
    return button(
      camera ? "拍攝銘牌" : "從照片選擇",
      () => file.click(),
      camera ? "" : "secondary",
    );
  }
  add(actions, chooser(true), chooser(false));
  add(
    box,
    actions,
    el(
      "p",
      "支援 JPG、PNG、HEIC，單張最多 20 MB。原始照片會完整保留。",
      "help",
    ),
  );
  root.append(box);
}

async function history(page = 1) {
  const data = await api(`/api/jobs?page=${page}`);
  root.replaceChildren(el("h1", "辨識紀錄"));
  if (!data.items.length) root.append(el("p", "還沒有辨識紀錄。", "empty"));
  else
    root.append(
      table(
        ["時間", "室外機型號", "狀態", "標記"],
        data.items.map((j) => [
          date(j.created_at),
          link(j.display_model || "尚未確認型號", `/jobs/${j.id}`),
          j.confirmed ? "已人工確認" : labels[j.status],
          `${j.scope === "BENCHMARK_SOURCE" ? "Benchmark · " : ""}${j.is_hard_example ? "待改善樣本" : "—"}`,
        ]),
      ),
    );
  const nav = el("div", null, "actions");
  if (page > 1)
    nav.append(
      button(
        "上一頁",
        guarded(() => history(page - 1)),
        "secondary",
      ),
    );
  if (data.has_next)
    nav.append(
      button(
        "下一頁",
        guarded(() => history(page + 1)),
        "secondary",
      ),
    );
  root.append(nav);
}

async function sharePanel(confirmation, job) {
  await loadComponent("sharing");
  const sharing = window.NameplateSharing;
  const box = panel("分享已確認資料");
  box.id = "share-panel";
  const data = await api(`/api/confirmations/${confirmation.id}/share-text`);
  const feedback = el("p", "正在準備原始相片…", "help");
  feedback.setAttribute("role", "status");
  const preview = el("details");
  const text = el("textarea");
  text.rows = 9;
  text.readOnly = true;
  text.value = data.text;
  text.setAttribute("aria-label", "LINE 分享文字");
  const recordUrl = new URL(`/jobs/${job.id}`, location.href).href;
  const recordLink = el("textarea");
  recordLink.rows = 2;
  recordLink.readOnly = true;
  recordLink.value = recordUrl;
  recordLink.setAttribute("aria-label", "辨識紀錄連結");
  add(
    preview,
    el("summary", "查看分享文字與紀錄連結"),
    text,
    labeled("辨識紀錄連結", recordLink),
    el("p", "紀錄連結仍需通過這個系統的存取驗證。", "help"),
  );

  const copy = async (value, target, label) => {
    const result = await sharing.copyText(value, target);
    if (result.copied) {
      feedback.textContent = `已複製${label}，可貼到 LINE。`;
      notice(`已複製${label}。`);
    } else {
      preview.open = true;
      target.focus();
      target.select();
      target.setSelectionRange(0, target.value.length);
      feedback.textContent =
        "瀏覽器未允許自動複製，已選取內容，請長按選擇「複製」。";
    }
  };

  let original = null;
  let disposed = false;
  const originalRequest = new AbortController();
  box.dispose = () => {
    disposed = true;
    originalRequest.abort();
    sharing.releaseOriginal(original);
  };
  const fallback = el("div", null, "share-fallback");
  fallback.hidden = true;
  const download = link(
    "1. 儲存原始相片",
    job.original_image_url,
    "button secondary",
  );
  download.download = "";
  const openOriginal = link("開啟原圖，長按儲存或分享", job.original_image_url);
  openOriginal.target = "_blank";
  openOriginal.rel = "noopener";
  const line = link(
    "2. 開啟 LINE 帶入文字",
    sharing.lineTextUrl(data.text),
    "button",
  );
  line.target = "_blank";
  line.rel = "noopener noreferrer";
  add(
    fallback,
    el(
      "p",
      "此瀏覽器請分兩步分享：先儲存原圖，再開啟 LINE，附上相片與以下文字。",
      "help",
    ),
    add(el("div", null, "actions"), download, line),
    openOriginal,
    el("p", "LINE 文字按鈕不會自動附上照片，請從相簿或檔案加入原圖。", "help"),
  );

  const share = button(
    "準備原始相片…",
    guarded(async () => {
      if (!original) return;
      share.disabled = true;
      try {
        // The file is already loaded; invoke the share sheet inside this click.
        const result = await sharing.shareConfirmed({
          file: original.file,
          text: data.text,
          title: "大金空調設備資料",
        });
        if (result.status === "shared") {
          feedback.textContent =
            "已交給手機分享功能，請在 LINE 確認相片與文字後傳送。若只帶入相片，可再複製文字貼上。";
        } else if (result.status === "cancelled") {
          feedback.textContent = "已取消分享，可以再次操作。";
        } else {
          fallback.hidden = false;
          feedback.textContent =
            "這次無法開啟原生圖文分享，請使用下方的原圖與 LINE 操作。";
        }
      } finally {
        share.disabled = false;
      }
    }),
  );
  share.disabled = true;
  const actions = add(
    el("div", null, "actions share-actions"),
    share,
    button(
      "複製文字",
      guarded(() => copy(data.text, text, "文字")),
      "secondary",
    ),
    button(
      "複製紀錄連結",
      guarded(() => copy(recordUrl, recordLink, "紀錄連結")),
      "secondary",
    ),
  );
  add(
    box,
    actions,
    feedback,
    fallback,
    preview,
    el(
      "p",
      `分享人工確認第 ${confirmation.revision_no} 版。內容修改後需再次確認。`,
      "help",
    ),
  );

  sharing
    .prepareOriginal({
      url: job.original_image_url,
      filename: `nameplate-${job.id}`,
      signal: originalRequest.signal,
    })
    .then((prepared) => {
      if (disposed) {
        sharing.releaseOriginal(prepared);
        return;
      }
      original = prepared;
      download.href = original.url;
      download.download = original.filename;
      if (sharing.canShareFiles(original.file)) {
        share.textContent = "分享原圖與文字";
        share.disabled = false;
        feedback.textContent = "原始相片已備妥，按分享後選擇 LINE。";
      } else {
        share.hidden = true;
        fallback.hidden = false;
        feedback.textContent = "原始相片已備妥，可儲存後與確認文字一起傳送。";
      }
    })
    .catch((error) => {
      if (disposed || error.name === "AbortError") return;
      share.hidden = true;
      fallback.hidden = false;
      feedback.textContent =
        "原始相片暫時無法載入。可用下方連結重開原圖，或重新整理後再試；尚未送出照片。";
    });
  return box;
}

function recognitionLoading(job, attempt, view) {
  const box = panel();
  box.classList.add("recognition-loading");
  box.id = "recognition-loading";
  box.setAttribute("aria-busy", "true");
  const spinner = el("div", null, "loading-spinner");
  spinner.setAttribute("aria-hidden", "true");
  const stage = el("p", "", "loading-stage");
  stage.setAttribute("role", "status");
  stage.setAttribute("aria-live", "polite");
  const messages = {
    QUEUED: "照片已保存，正在等待開始辨識。",
    PREPROCESSING: "正在處理照片，準備讀取銘牌。",
    RUNNING: "AI 正在讀取銘牌資料，請稍候。",
  };
  const update = (status) => {
    const message = messages[status] || "正在取得辨識狀態…";
    if (stage.textContent !== message) stage.textContent = message;
  };
  update(attempt.status);
  add(
    box,
    spinner,
    el("h2", "辨識中"),
    stage,
    el(
      "p",
      "照片已保存。完成後會自動顯示結果，也可以稍後從辨識紀錄開啟。",
      "help",
    ),
    link("查看辨識紀錄", "/history", "button secondary"),
  );
  root.append(box);
  loadComponent("polling")
    .then(() => {
      if (view !== jobView) return;
      const current = (data) => {
        const found = data.attempts.find((item) => item.id === attempt.id);
        if (!found) throw new Error("暫時無法取得這次辨識，正在重新連線…");
        return found;
      };
      stopRecognition = window.NameplatePolling.watch({
        load: (signal) => api(`/api/jobs/${job.id}`, { signal }),
        isPending: (data) =>
          ["QUEUED", "PREPROCESSING", "RUNNING"].includes(current(data).status),
        onProgress: (data) => update(current(data).status),
        onComplete: guarded((data) => jobPage(job.id, attempt.id, data)),
        onError: () => {
          stage.textContent =
            "連線暫時中斷，正在重新取得狀態。照片已保存，無需再次上傳。";
        },
      });
    })
    .catch((error) => {
      if (view !== jobView) return;
      stage.textContent = error.message;
      box.setAttribute("aria-busy", "false");
      box.append(
        button(
          "重新取得狀態",
          guarded(() => jobPage(job.id, attempt.id)),
          "secondary",
        ),
      );
    });
}

async function jobPage(id, selectedId, receivedJob) {
  const view = ++jobView;
  stopRecognition();
  disposeShare();
  disposeShare = () => {};
  const job = receivedJob || (await api(`/api/jobs/${id}`));
  if (view !== jobView) return;
  root.replaceChildren(el("h1", "銘牌辨識結果"));
  const attempt =
    job.attempts.find((a) => a.id === selectedId) || job.attempts.at(-1);
  if (!attempt) return;
  const top = panel();
  top.classList.add("recognition-meta");
  const stateBadge = el("span", labels[attempt.status], "badge");
  add(
    top,
    stateBadge,
    el(
      "p",
      `${attempt.provider} · ${attempt.model || "未設定模型"} · ${attempt.prompt_version}`,
      "help",
    ),
  );
  if (job.attempts.length > 1) {
    const choices = select(
      job.attempts.map((a, i) => [
        a.id,
        `第 ${i + 1} 次 · ${a.provider} · ${a.model || "未設定"}`,
      ]),
      attempt.id,
    );
    choices.addEventListener(
      "change",
      guarded(() => jobPage(id, choices.value)),
    );
    top.append(labeled("辨識版本", choices));
  }
  root.append(top);
  if (["QUEUED", "PREPROCESSING", "RUNNING"].includes(attempt.status)) {
    stateBadge.textContent = "辨識中";
    recognitionLoading(job, attempt, view);
    return;
  }
  const split = el("div", null, "split"),
    photo = el("details", null, "panel photo-column"),
    form = el("div");
  photo.open = window.matchMedia("(min-width: 721px)").matches;
  photo.append(el("summary", "查看照片，對照辨識內容"));
  form.className = "review-fields";
  form.append(el("h2", "確認辨識內容"));
  const img = el("img", null, "photo");
  img.src = attempt.processed_image_url || job.original_image_url;
  img.alt = "上傳的銘牌照片";
  img.addEventListener(
    "error",
    () => {
      img.hidden = true;
      photo.append(el("p", "瀏覽器無法預覽此格式，可下載原圖查看。", "help"));
    },
    { once: true },
  );
  add(
    photo,
    img,
    link("開啟原始照片", job.original_image_url, "button secondary"),
  );
  const difficulty = select(
    [
      ["UNLABELED", "尚未標記"],
      ["EASY", "EASY"],
      ["MEDIUM", "MEDIUM"],
      ["HARD", "HARD"],
    ],
    job.image_difficulty,
  );
  difficulty.addEventListener(
    "change",
    guarded(async () => {
      await api(`/api/jobs/${id}`, {
        method: "PATCH",
        body: { image_difficulty: difficulty.value },
      });
      notice("已儲存照片難度。");
    }),
  );
  photo.append(labeled("照片難度（人工標記）", difficulty));
  add(split, form, photo);
  root.append(split);
  if (attempt.status === "FAILED") {
    const failure = panel("辨識失敗");
    add(
      failure,
      el("p", attempt.error_message, "error"),
      el("p", "可重新辨識、重新拍照，或直接依照片填寫後確認。", "help"),
    );
    form.append(failure);
  } else
    form.append(
      el(
        "p",
        "請逐欄核對。AI 信心只供參考；空白欄位可標記未標示、無法辨讀或尚未核對。",
        "help",
      ),
    );
  const revisions = await api(`/api/jobs/${id}/confirmations`);
  if (view !== jobView) return;
  const confirmed = revisions.items.find((c) => c.attempt_id === attempt.id);
  if (confirmed)
    stateBadge.textContent = `已人工確認 · 第 ${confirmed.revision_no} 版`;
  const fields = attempt.normalized_ai_result?.fields || {};
  const controls = {};
  const grid = el("div", null, "grid");
  reviewMs = 0;
  activeSince = performance.now();
  for (const spec of config.fields) {
    const ai = fields[spec.name] || {
      value: null,
      confidence: "UNKNOWN",
      raw_text: null,
    };
    const human = confirmed?.human_ground_truth.fields[spec.name];
    const saved = confirmed?.annotations.find(
      (a) => a.field_name === spec.name,
    );
    const card = el("div", null, `field ${ai.confidence.toLowerCase()}`);
    const value = input("text", human?.value ?? ai.value ?? "");
    value.id = `field-${spec.name}`;
    value.maxLength = 200;
    if (spec.type !== "str") value.inputMode = "decimal";
    const name = el("label", `${spec.label}${spec.core ? " ★" : ""}`);
    name.htmlFor = value.id;
    add(
      card,
      el(
        "span",
        `${{ HIGH: "●", MEDIUM: "●", LOW: "●", UNKNOWN: "○" }[ai.confidence]} ${ai.confidence}`,
        `badge ${ai.confidence}`,
      ),
      name,
    );
    add(
      card,
      add(el("div", null, "unit-input"), value, el("span", spec.unit || "")),
    );
    const status = select(
      [
        ["KNOWN", "已核實數值"],
        ["NOT_PRESENT", "銘牌未標示"],
        ["UNREADABLE", "無法辨讀"],
        ["UNREVIEWED", "尚未核對"],
      ],
      human?.annotation_status || (ai.value !== null ? "KNOWN" : "UNREVIEWED"),
    );
    add(card, labeled("標註狀態", status));
    const details = el("details");
    add(
      details,
      el("summary", "AI 依據與修正原因"),
      el("small", `AI 原值：${ai.value ?? "null"}`),
      el("small", `AI 依據：${ai.raw_text || "未提供"}`),
    );
    const reason = select(
      config.correction_types.map((k) => [k, `${k} · ${correctionLabels[k]}`]),
      saved?.correction_type || "UNKNOWN",
    );
    const note = input("text", saved?.note || "");
    note.maxLength = 2000;
    add(
      details,
      labeled("原因（不確定可保留 UNKNOWN）", reason),
      labeled("備註（選填）", note),
    );
    card.append(details);
    attempt.validation_result
      .filter((w) => w.field === spec.name)
      .forEach((w) => card.append(el("p", w.message, "warning")));
    value.addEventListener("input", () => {
      status.value = value.value.trim() ? "KNOWN" : "UNREVIEWED";
      trackDirty();
    });
    [status, reason, note].forEach((n) =>
      n.addEventListener("change", trackDirty),
    );
    controls[spec.name] = { value, status, reason, note };
    grid.append(card);
  }
  form.append(grid);
  const actions = panel("確認與儲存");
  actions.id = "confirmation-actions";
  actions.classList.add("confirmation-actions");
  const confirmationHint = el(
    "p",
    confirmed
      ? `已儲存第 ${confirmed.revision_no} 版；修改內容後請再次確認。`
      : "請核對下方內容，按確認後即可分享原圖與文字。",
    "help",
  );
  confirmationHint.id = "confirmation-hint";
  const save = button(
    "確認資料並儲存",
    guarded(async () => {
      save.disabled = true;
      try {
        accrue();
        const values = {};
        for (const spec of config.fields) {
          const c = controls[spec.name];
          values[spec.name] = {
            value: c.value.value.trim() || null,
            unit: c.value.value.trim() ? spec.unit : null,
            annotation_status: c.status.value,
            correction_type: c.reason.value,
            note: c.note.value,
          };
        }
        const result = await api(`/api/jobs/${id}/confirmations`, {
          method: "POST",
          body: {
            attempt_id: attempt.id,
            expected_revision: job.revision,
            fields: values,
            review_active_ms: Math.round(reviewMs),
          },
        });
        if (view !== jobView) return;
        dirty = false;
        notice(`已儲存人工確認第 ${result.revision_no} 版。`);
        await jobPage(id, attempt.id);
        document
          .querySelector("#share-panel")
          ?.scrollIntoView({ block: "start" });
      } finally {
        save.disabled = false;
      }
    }),
  );
  add(actions, confirmationHint, save);
  root.insertBefore(actions, top);
  if (confirmed) {
    try {
      const sharing = await sharePanel(confirmed, job);
      if (view !== jobView) {
        sharing.dispose();
        return;
      }
      disposeShare = () => sharing.dispose();
      sharing.hidden = dirty;
      root.insertBefore(sharing, actions);
    } catch (error) {
      if (view !== jobView) return;
      const failedShare = panel("分享資料暫時無法載入");
      add(
        failedShare,
        el("p", error.message, "error"),
        button(
          "重新載入分享資料",
          guarded(() => jobPage(id, attempt.id)),
          "secondary",
        ),
      );
      root.insertBefore(failedShare, actions);
    }
  }
  const retry = panel("重新辨識");
  const profile = profileSelect();
  add(
    retry,
    profile,
    add(
      el("div", null, "actions"),
      button(
        "重新辨識",
        guarded(async () => {
          await api(`/api/jobs/${id}/attempts`, {
            method: "POST",
            body: { profile_id: profile.value },
          });
          if (view !== jobView) return;
          dirty = false;
          await jobPage(id);
        }),
        "secondary",
      ),
      link("重新拍照", "/", "button secondary"),
    ),
  );
  form.append(retry);
  if (revisions.items.length)
    form.append(jsonDetails("人工確認與逐欄修改歷程", revisions.items));
  if (config.debug_data) {
    const debug = panel();
    debug.append(
      button(
        "查看開發除錯資料",
        guarded(async () =>
          debug.append(
            jsonDetails(
              "模型原始回覆與標準化結果",
              await api(`/api/attempts/${attempt.id}/debug`),
            ),
          ),
        ),
        "secondary",
      ),
    );
    form.append(debug);
  }
}

async function dashboardPage() {
  const d = await api("/api/dashboard");
  root.replaceChildren(el("h1", "模型表現與人工修正"));
  const stats = el("div", null, "stats");
  for (const [label, value] of [
    ["辨識工作", d.total_jobs],
    ["人工確認", d.confirmed_samples],
    ["已核實且未修改", d.fully_correct_samples],
    ["有修正樣本", d.corrected_samples],
    ["待改善樣本", d.hard_examples],
    ["工作修正率", rate(d.correction_rate)],
    ["平均辨識時間", seconds(d.average_processing_ms)],
    ["平均人工確認時間", seconds(d.average_human_review_ms)],
  ])
    add(
      stats,
      add(el("div", null, "stat"), el("p", label), el("strong", value)),
    );
  root.append(stats);
  const ranking = panel("欄位修正率排名");
  ranking.append(
    table(
      ["欄位", "修正率"],
      d.field_error_ranking.map((x) => [x.label, rate(x)]),
    ),
  );
  root.append(ranking);
  for (const [title, data] of [
    ["依模型", d.correction_by_model],
    ["依照片難度", d.correction_by_difficulty],
  ])
    root.append(
      add(
        panel(`修正率 · ${title}`),
        table(
          [title, "修正率"],
          Object.entries(data).map(([k, v]) => [k, rate(v)]),
        ),
      ),
    );
  add(
    root,
    add(
      panel("Provider 使用量"),
      table(["Provider", "次數"], Object.entries(d.provider_usage)),
    ),
    add(
      panel("人工標記的錯誤原因"),
      table(["原因", "次數"], Object.entries(d.correction_types)),
    ),
    el("p", d.counting_policy, "help"),
  );
}

async function datasetsPage() {
  const data = await api("/api/datasets");
  root.replaceChildren(el("h1", "私有資料集"));
  const box = panel("建立不可覆寫的資料集版本");
  const category = select([
    ["benchmark", "benchmark · 人工確認的比較樣本"],
    ["confirmed", "confirmed · 人工未修改"],
    ["corrected", "corrected · 人工有修正"],
    ["low_confidence", "low_confidence · AI 低信心"],
    ["failed", "failed · 辨識失敗"],
  ]);
  const split = select([
    ["DEVELOPMENT", "調整集（DEVELOPMENT）"],
    ["HOLDOUT", "保留驗收集（HOLDOUT）"],
  ]);
  const version = input("text");
  version.placeholder = "例如 dataset_v001；留白自動命名";
  const ids = el("textarea");
  ids.rows = 2;
  ids.placeholder =
    "選填：照片工作 ID，以逗號分隔。不填則取最近符合條件的照片，最多 100 筆。";
  add(
    box,
    labeled("類別", category),
    labeled("分組", split),
    labeled("版本名稱", version),
    labeled("指定照片", ids),
    el(
      "p",
      "未經確認的失敗或低信心樣本不會變成 Ground Truth。未核對、無法辨讀的欄位不納入有答案的評分。",
      "help",
    ),
  );
  const create = button(
    "建立私有資料集",
    guarded(async () => {
      create.disabled = true;
      try {
        const body = { category: category.value, split: split.value };
        if (version.value.trim()) body.version = version.value.trim();
        if (ids.value.trim())
          body.job_ids = ids.value
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
        const result = await api("/api/datasets", { method: "POST", body });
        notice(`已建立 ${result.version}，共 ${result.sample_count} 筆。`);
        await datasetsPage();
      } finally {
        create.disabled = false;
      }
    }),
  );
  box.append(create);
  add(
    root,
    box,
    table(
      ["版本", "類別／分組", "照片數", "檔案"],
      data.items.map((d) => [
        d.version,
        `${d.category} / ${d.split}`,
        d.sample_count,
        link("下載私人 ZIP", `/api/datasets/${d.id}/download`),
      ]),
    ),
  );
}

async function benchmarkPage(selected) {
  const [versions, experiments] = await Promise.all([
    api("/api/datasets"),
    api("/api/benchmarks"),
  ]);
  root.replaceChildren(el("h1", "固定資料集 Benchmark"));
  const box = panel("比較模型與 Prompt");
  const eligible = versions.items.filter((d) => d.category === "benchmark");
  if (!eligible.length) {
    add(
      box,
      el("p", "先確認照片並建立 Benchmark 資料集。"),
      link("建立資料集", "/datasets", "button secondary"),
    );
  } else {
    const dataset = select(
      eligible.map((d) => [
        d.id,
        `${d.version} · ${d.sample_count} 張 · ${d.split}`,
      ]),
    );
    box.append(labeled("固定資料集", dataset));
    const checks = [];
    for (const p of config.profiles) {
      const check = input("checkbox");
      check.checked = p.id === config.default_profile;
      checks.push([p.id, check]);
      add(
        box,
        add(
          el("label", null, "check-option"),
          check,
          document.createTextNode(`${p.provider} · ${p.model || "未設定"}`),
        ),
      );
    }
    box.append(
      button(
        "開始比較",
        guarded(async () => {
          const result = await api("/api/benchmarks", {
            method: "POST",
            body: {
              dataset_id: dataset.value,
              profiles: checks.filter(([, c]) => c.checked).map(([id]) => id),
            },
          });
          await benchmarkPage(result.id);
        }),
      ),
    );
  }
  root.append(box);
  if (experiments.items.length) {
    const picker = select(
      [
        ["", "選擇比較紀錄"],
        ...experiments.items.map((b) => [
          b.id,
          `${date(b.created_at)} · ${b.targets.join(" / ")}`,
        ]),
      ],
      selected || "",
    );
    picker.addEventListener(
      "change",
      guarded(() => benchmarkPage(picker.value)),
    );
    root.append(picker);
  }
  if (selected) await renderBenchmark(selected, experiments.items);
}

async function renderBenchmark(id, experiments) {
  const data = await api(`/api/benchmarks/${id}`);
  const holder = panel(data.dataset_version);
  holder.id = "benchmark-result";
  holder.append(
    el(
      "p",
      data.complete ? "比較已完成" : "比較進行中，可稍後回到此頁。",
      data.complete ? "success" : "warning",
    ),
  );
  holder.append(
    table(
      [
        "模型",
        "核心逐欄正確率",
        "六欄全對率",
        "空值率",
        "人工審查幻覺率",
        "平均延遲",
        "失敗",
      ],
      Object.entries(data.reports).map(([k, r]) => [
        k,
        rate(r.core_field_accuracy),
        rate(r.exact_match_accuracy),
        rate(r.null_rate),
        rate(r.hallucination_rate),
        seconds(r.average_latency_ms),
        `${r.failure_count}/${r.sample_count}`,
      ]),
    ),
  );
  holder.append(
    el(
      "p",
      "正確率只以已核實的已知值計算；辨識失敗仍列入分母。幻覺率未人工審查前顯示尚無資料。",
      "help",
    ),
  );
  for (const [target, r] of Object.entries(data.reports)) {
    const d = el("details");
    add(
      d,
      el("summary", `${target} · 逐欄與難度結果`),
      table(
        ["欄位", "已知值正確率", "正確留空率", "基準差異率"],
        config.fields.map((f) => [
          f.label,
          rate(r.per_field[f.name].accuracy),
          rate(r.per_field[f.name].absence_accuracy),
          rate(r.per_field[f.name].correction_rate),
        ]),
      ),
      table(
        ["照片難度", "張數", "核心逐欄正確率"],
        Object.entries(r.by_difficulty).map(([k, v]) => [
          k,
          v.sample_count,
          rate(v.core_field_accuracy),
        ]),
      ),
    );
    holder.append(d);
  }
  const baselines = experiments.filter(
    (b) => b.dataset_id === data.dataset_id && b.id !== id,
  );
  if (data.complete && baselines.length) {
    const compareBox = panel("逐欄回歸比較");
    const baseline = select(baselines.map((b) => [b.id, date(b.created_at)]));
    const before = select(baselines[0].targets.map((t) => [t, t]));
    baseline.addEventListener("change", () => {
      before.replaceChildren();
      baselines
        .find((b) => b.id === baseline.value)
        .targets.forEach((t) => {
          const o = el("option", t);
          o.value = t;
          before.append(o);
        });
    });
    const after = select(Object.keys(data.targets).map((t) => [t, t]));
    add(
      compareBox,
      labeled("先前 Benchmark", baseline),
      labeled("先前模型", before),
      labeled("本次模型", after),
      button(
        "檢查是否退步",
        guarded(async () => {
          const params = new URLSearchParams({
            baseline: baseline.value,
            baseline_target: before.value,
            target: after.value,
          });
          const result = await api(`/api/benchmarks/${id}/compare?${params}`);
          compareBox.querySelector(".comparison")?.remove();
          const out = el("div", null, "comparison");
          add(
            out,
            el(
              "p",
              `結果：${result.status}`,
              result.status === "PASS" ? "success" : "warning",
            ),
            table(
              ["欄位", "之前", "之後", "差異"],
              Object.entries(result.fields).map(([n, v]) => [
                config.fields.find((f) => f.name === n).label,
                rate(v.before),
                rate(v.after),
                v.delta === null ? "—" : `${(v.delta * 100).toFixed(1)} 百分點`,
              ]),
            ),
            el("p", "樣本不足時不判定通過；報告不會自動更換部署模型。", "help"),
          );
          compareBox.append(out);
        }),
        "secondary",
      ),
    );
    holder.append(compareBox);
  }
  for (const item of data.items) {
    const detail = el("details");
    add(
      detail,
      el(
        "summary",
        `${item.target_id} · ${item.image_difficulty} · ${labels[item.status]} · ${seconds(item.latency_ms)}`,
      ),
      link("開啟圖片與辨識資料", `/jobs/${item.job_id}`),
      jsonDetails("AI 結果", item.ai_result),
      jsonDetails("固定人工答案", item.ground_truth),
    );
    if (item.status === "SUCCEEDED") {
      const field = select(config.fields.map((f) => [f.name, f.label]));
      const judgment = select([
        ["UNREVIEWED", "尚未審查"],
        ["SUPPORTED", "有影像依據"],
        ["UNSUPPORTED", "無影像依據"],
      ]);
      add(
        detail,
        el(
          "p",
          "幻覺指標需人工核對影像依據；辨識字元錯誤不會自動算作幻覺。",
          "help",
        ),
        labeled("審查欄位", field),
        labeled("影像依據", judgment),
        button(
          "儲存依據審查",
          guarded(async () => {
            await api(`/api/benchmark-items/${item.id}/assessments`, {
              method: "POST",
              body: { fields: { [field.value]: judgment.value } },
            });
            notice("已保存人工審查，可重新開啟報告查看指標。");
          }),
          "secondary",
        ),
      );
    }
    holder.append(detail);
  }
  root.append(holder);
  if (!data.complete)
    setTimeout(
      guarded(async () => {
        if (
          document.querySelector("#benchmark-result") &&
          location.pathname === "/benchmark"
        ) {
          document.querySelector("#benchmark-result").remove();
          await renderBenchmark(id, experiments);
        }
      }),
      3000,
    );
}

async function start() {
  config = await api("/api/bootstrap");
  const path = location.pathname;
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.getAttribute("href") === path) a.setAttribute("aria-current", "page");
  });
  if (path.startsWith("/jobs/")) await jobPage(path.split("/")[2]);
  else if (path === "/history") await history();
  else if (path === "/dashboard") await dashboardPage();
  else if (path === "/datasets") await datasetsPage();
  else if (path === "/benchmark") await benchmarkPage();
  else home();
}
guarded(start)();
