/* Photo review helpers: text summaries have no inferred image coordinates. */
(function (window) {
  "use strict";

  function duration(ms) {
    return Number.isFinite(ms) && ms >= 0
      ? `${(ms / 1000).toFixed(1)} 秒`
      : "尚無紀錄";
  }

  function timingRows(attempt) {
    const hasTotal = [attempt.processing_ms, attempt.queue_ms].every(
      (value) => Number.isFinite(value) && value >= 0,
    );
    return [
      ["辨識處理（含 AI）", duration(attempt.processing_ms)],
      ["AI 回應", duration(attempt.latency_ms)],
      ["排隊", duration(attempt.queue_ms)],
      [
        "本次總耗時（含排隊）",
        duration(hasTotal ? attempt.processing_ms + attempt.queue_ms : null),
      ],
    ];
  }

  function initialValue(ai, human) {
    // A human-cleared value must stay empty rather than fall back to the AI.
    return human ? (human.value ?? "") : (ai?.value ?? "");
  }

  function fieldSpecs(attempt, fallback) {
    // The saved attempt owns its scope, including failed and legacy attempts.
    return Array.isArray(attempt.field_metadata) && attempt.field_metadata.length
      ? attempt.field_metadata
      : fallback;
  }

  function tokenRows(usage = {}) {
    const count = (value) =>
      Number.isInteger(value) && value >= 0 ? value.toLocaleString("zh-TW") : "未提供";
    return [
      ["輸入 Token", count(usage?.input_tokens)],
      ["輸出 Token", count(usage?.output_tokens)],
      ["總 Token", count(usage?.total_tokens)],
    ];
  }

  function failurePresentation(attempt) {
    if (attempt.error_code === "PROVIDER_QUOTA_EXHAUSTED") {
      const provider = { nvidia: "NIM", gemini: "Gemini" }[attempt.provider] || "模型服務";
      return {
        title: `${provider} 額度不足`,
        help: `請確認 ${provider} 帳戶額度後重新辨識，或切換其他已設定的模型；也可以依照片人工填寫。`,
        quota: true,
      };
    }
    if (attempt.error_code === "PROVIDER_RATE_LIMITED") {
      return {
        title: "暫時受到流量限制",
        help: "模型服務暫時限制請求，請稍後重新辨識，或切換其他已設定的模型、依照片人工填寫。",
        quota: false,
      };
    }
    return {
      title: "辨識失敗",
      help: "可重新辨識、重新拍照，或直接依照片填寫後確認。",
      quota: false,
    };
  }

  function createPreview({ specs, fields, onActivate, document = window.document }) {
    const root = document.createElement("section");
    root.className = "photo-transcript";
    root.setAttribute("aria-label", "照片文字摘要，點選可校正對應欄位");
    const heading = document.createElement("h3");
    heading.textContent = "銘牌文字預覽";
    const hint = document.createElement("p");
    hint.className = "help";
    hint.textContent = "點選文字可跳到下方修改。AI 文字仍需對照照片核實。";
    const unsaved = document.createElement("p");
    unsaved.className = "warning preview-unsaved";
    unsaved.textContent = "以下顯示目前草稿，尚未儲存。請確認資料後再分享。";
    unsaved.setAttribute("role", "status");
    unsaved.hidden = true;
    const list = document.createElement("div");
    list.className = "transcript-fields";
    const empty = document.createElement("p");
    empty.className = "help transcript-empty";
    empty.textContent = "目前沒有可預覽的文字，請依照片在下方填寫；填入後會同步顯示。";
    const entries = new Map();
    for (const spec of specs) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "transcript-field";
      row.setAttribute("aria-controls", `field-${spec.name}`);
      row.addEventListener("click", () => onActivate(spec.name));
      const label = document.createElement("span");
      label.className = "transcript-label";
      label.textContent = spec.label;
      const value = document.createElement("strong");
      value.className = "transcript-value";
      const confidence = document.createElement("span");
      const level = fields[spec.name]?.confidence || "UNKNOWN";
      confidence.className = `badge ${level}`;
      confidence.textContent = `AI ${level}`;
      const source = document.createElement("span");
      source.className = "transcript-source";
      row.append(label, value, confidence, source);
      row.hidden = true;
      list.append(row);
      entries.set(spec.name, { row, value, source, spec });
    }
    root.append(heading, hint, unsaved, list, empty);

    function update(name, value, { edited = false, confirmed = false } = {}) {
      const entry = entries.get(name);
      if (!entry) return;
      const text = value === null || value === undefined ? "" : String(value).trim();
      const display = text ? `${text}${entry.spec.unit ? ` ${entry.spec.unit}` : ""}` : "";
      entry.row.hidden = !text;
      entry.value.textContent = display;
      entry.source.textContent = edited
        ? "修改草稿 · 未儲存"
        : confirmed
          ? "已儲存的確認內容"
          : "AI 辨識 · 待核對";
      entry.row.classList.toggle("is-edited", edited);
      entry.row.setAttribute("aria-label", `校正${entry.spec.label}：${display}`);
      empty.hidden = [...entries.values()].some((item) => !item.row.hidden);
    }

    return {
      element: root,
      update,
      markUnsaved() {
        unsaved.hidden = false;
      },
    };
  }

  function createFieldNavigator({ controls, cards, reducedMotion = false }) {
    let highlighted = null;
    let timer = null;
    function dispose() {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      highlighted?.classList.remove("field-highlight");
      highlighted = null;
    }
    function activate(name) {
      const control = controls[name]?.value;
      const card = cards[name];
      if (!control || !card) return;
      dispose();
      highlighted = card;
      card.classList.add("field-highlight");
      try {
        control.focus({ preventScroll: true });
      } catch {
        control.focus();
      }
      card.scrollIntoView({
        block: "center",
        behavior: reducedMotion ? "auto" : "smooth",
      });
      timer = window.setTimeout(dispose, 2400);
    }
    return { activate, dispose };
  }

  function startElapsed({
    since,
    onTick,
    wallNow = () => Date.now(),
    now = () => window.performance.now(),
  }) {
    const timestamp = Date.parse(since);
    const initial = Number.isFinite(timestamp) ? Math.max(0, wallNow() - timestamp) : 0;
    const began = now();
    let timer = null;
    let stopped = false;
    function tick() {
      if (stopped) return;
      onTick(Math.floor((initial + Math.max(0, now() - began)) / 1000));
      timer = window.setTimeout(tick, 1000);
    }
    tick();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
  }

  window.NameplateReview = Object.freeze({
    timingRows,
    tokenRows,
    failurePresentation,
    initialValue,
    fieldSpecs,
    createPreview,
    createFieldNavigator,
    startElapsed,
  });
})(window);
