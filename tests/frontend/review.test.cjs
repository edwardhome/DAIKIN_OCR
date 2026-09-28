"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { runInNewContext } = require("node:vm");

const source = readFileSync(join(__dirname, "../../static/js/review.js"), "utf8");

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.textContent = "";
    this.className = "";
    const classes = new Set();
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle(name, enabled) {
        if (enabled) classes.add(name);
        else classes.delete(name);
      },
    };
  }
  append(...elements) {
    this.children.push(...elements);
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
  click() {
    this.listeners.click?.();
  }
  focus(options) {
    this.focused = true;
    this.focusOptions = options;
  }
  scrollIntoView(options) {
    this.scrollOptions = options;
  }
}

function load() {
  const timers = new Map();
  let timerId = 0;
  const document = { createElement: (tag) => new Element(tag) };
  const window = {
    document,
    setTimeout(callback, delay) {
      const id = ++timerId;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };
  runInNewContext(source, { window });
  return {
    review: window.NameplateReview,
    timers,
    fireNext() {
      const [id, timer] = [...timers][0];
      timers.delete(id);
      timer.callback();
    },
  };
}

const specs = [
  { name: "outdoor_model", label: "室外機型號", unit: null },
  { name: "refrigerant_charge", label: "冷媒量", unit: "kg" },
  { name: "serial_number", label: "序號", unit: null },
];

test("review honors the saved attempt scope, including failures and legacy records", () => {
  const { review } = load();
  const identity = [
    { name: "outdoor_model" }, { name: "indoor_model" }, { name: "serial_number" },
  ];
  assert.equal(review.fieldSpecs({ status: "FAILED", field_metadata: identity }, specs), identity);
  assert.equal(review.fieldSpecs({ field_metadata: specs }, identity), specs);
  assert.equal(review.fieldSpecs({}, specs), specs);
});

test("photo transcript exposes nonempty values, including zero, with field navigation", () => {
  const { review } = load();
  let activated;
  const preview = review.createPreview({
    specs,
    fields: { outdoor_model: { confidence: "LOW" } },
    onActivate: (name) => (activated = name),
  });
  const [, , , list, empty] = preview.element.children;
  assert.equal(empty.hidden, false);
  preview.update("outdoor_model", "RHF5ORVLT");
  preview.update("refrigerant_charge", 0);
  preview.update("serial_number", null);
  assert.equal(list.children[0].hidden, false);
  assert.equal(list.children[1].children[1].textContent, "0 kg");
  assert.equal(list.children[2].hidden, true);
  assert.equal(empty.hidden, true);
  assert.equal(list.children[0].children[2].textContent, "AI LOW");
  assert.equal(list.children[0].attributes["aria-controls"], "field-outdoor_model");
  list.children[0].click();
  assert.equal(activated, "outdoor_model");
});

test("draft updates stay synchronized, preserve the prediction and flag unsaved work", () => {
  const { review } = load();
  const prediction = { outdoor_model: { value: "RHF5ORVLT", confidence: "HIGH" } };
  const preview = review.createPreview({ specs, fields: prediction, onActivate() {} });
  const [, , warning, list, empty] = preview.element.children;
  preview.update("outdoor_model", prediction.outdoor_model.value);
  preview.update("outdoor_model", "RHF50RVLT", { edited: true });
  preview.markUnsaved();
  assert.equal(list.children[0].children[1].textContent, "RHF50RVLT");
  assert.equal(list.children[0].children[3].textContent, "修改草稿 · 未儲存");
  assert.equal(list.children[0].classList.contains("is-edited"), true);
  assert.equal(warning.hidden, false);
  assert.equal(prediction.outdoor_model.value, "RHF5ORVLT");
  preview.update("outdoor_model", "  ", { edited: true });
  assert.equal(list.children[0].hidden, true);
  assert.equal(empty.hidden, false);
});

test("transcript displays untrusted model text literally and identifies confirmed values", () => {
  const { review } = load();
  const preview = review.createPreview({ specs, fields: {}, onActivate() {} });
  const list = preview.element.children[3];
  const value = '<img src=x onerror="bad()">';
  preview.update("serial_number", value, { confirmed: true });
  assert.equal(list.children[2].children[1].textContent, value);
  assert.equal(list.children[2].children[1].children.length, 0);
  assert.equal(list.children[2].children[3].textContent, "已儲存的確認內容");
});

test("a confirmed null stays empty instead of reviving the machine prediction", () => {
  const { review } = load();
  const ai = { value: "RHF50RVLT" };
  assert.equal(review.initialValue(ai, { value: null }), "");
  assert.equal(review.initialValue(ai, undefined), "RHF50RVLT");
  assert.equal(review.initialValue({ value: 0 }, undefined), 0);
  assert.equal(review.initialValue(ai, { value: 0 }), 0);
});

test("activating a transcript entry focuses, scrolls and briefly highlights its exact field", () => {
  const { review, timers, fireNext } = load();
  const first = new Element("input");
  const second = new Element("input");
  const firstCard = new Element("div");
  const secondCard = new Element("div");
  const nav = review.createFieldNavigator({
    controls: { outdoor_model: { value: first }, serial_number: { value: second } },
    cards: { outdoor_model: firstCard, serial_number: secondCard },
    reducedMotion: true,
  });
  nav.activate("outdoor_model");
  assert.equal(first.focused, true);
  assert.equal(first.focusOptions.preventScroll, true);
  assert.equal(firstCard.scrollOptions.behavior, "auto");
  assert.equal(firstCard.classList.contains("field-highlight"), true);
  nav.activate("serial_number");
  assert.equal(firstCard.classList.contains("field-highlight"), false);
  assert.equal(second.focused, true);
  assert.equal(secondCard.classList.contains("field-highlight"), true);
  assert.equal(timers.size, 1);
  fireNext();
  assert.equal(secondCard.classList.contains("field-highlight"), false);
  nav.activate("serial_number");
  nav.dispose();
  assert.equal(timers.size, 0);
  assert.equal(secondCard.classList.contains("field-highlight"), false);
});

test("elapsed waiting includes existing queue time and stops ticking when disposed", () => {
  const { review, timers, fireNext } = load();
  let now = 0;
  const ticks = [];
  const stop = review.startElapsed({
    since: "2026-09-28T00:00:00Z",
    wallNow: () => Date.parse("2026-09-28T00:01:00Z"),
    now: () => now,
    onTick: (seconds) => ticks.push(seconds),
  });
  assert.deepEqual(ticks, [60]);
  now += 1000;
  fireNext();
  assert.deepEqual(ticks, [60, 61]);
  assert.equal(timers.size, 1);
  const lateCallback = [...timers.values()][0].callback;
  stop();
  stop();
  lateCallback();
  assert.equal(timers.size, 0);
  assert.deepEqual(ticks, [60, 61]);
});

test("missing timestamps and clock skew cannot display NaN or negative elapsed time", () => {
  const { review } = load();
  for (const since of [undefined, "invalid", "2030-01-01T00:00:00Z"]) {
    let result;
    const stop = review.startElapsed({
      since,
      wallNow: () => 0,
      now: () => 0,
      onTick: (seconds) => (result = seconds),
    });
    assert.equal(result, 0);
    stop();
  }
});

test("timing separates model latency from processing and queue, without double counting", () => {
  const { review } = load();
  const rows = review.timingRows({ processing_ms: 1200, latency_ms: 1000, queue_ms: 800 });
  assert.deepEqual(Array.from(rows, (row) => row[1]), ["1.2 秒", "1.0 秒", "0.8 秒", "2.0 秒"]);
  const missing = review.timingRows({ processing_ms: null, latency_ms: undefined, queue_ms: 0 });
  assert.deepEqual(Array.from(missing, (row) => row[1]), ["尚無紀錄", "尚無紀錄", "0.0 秒", "尚無紀錄"]);
});

test("token counts preserve real zero and do not invent missing or invalid usage", () => {
  const { review } = load();
  for (const usage of [undefined, null, {}]) {
    assert.deepEqual(Array.from(review.tokenRows(usage), (row) => row[1]), ["未提供", "未提供", "未提供"]);
  }
  assert.deepEqual(
    Array.from(review.tokenRows({ input_tokens: 1200, output_tokens: 0, total_tokens: 1200 }), (row) => row[1]),
    ["1,200", "0", "1,200"],
  );
  assert.deepEqual(
    Array.from(review.tokenRows({ input_tokens: -1, output_tokens: 1.5, total_tokens: "1200" }), (row) => row[1]),
    ["未提供", "未提供", "未提供"],
  );
});

test("only an explicit quota exhaustion receives the NIM quota warning", () => {
  const { review } = load();
  const quota = review.failurePresentation({ provider: "nvidia", error_code: "PROVIDER_QUOTA_EXHAUSTED" });
  assert.equal(quota.title, "NIM 額度不足");
  assert.equal(quota.quota, true);
  const gemini = review.failurePresentation({ provider: "gemini", error_code: "PROVIDER_QUOTA_EXHAUSTED" });
  assert.equal(gemini.title, "Gemini 額度不足");
  assert.doesNotMatch(gemini.help, /NIM/);
  const limited = review.failurePresentation({ error_code: "PROVIDER_RATE_LIMITED" });
  assert.equal(limited.quota, false);
  assert.equal(limited.title, "暫時受到流量限制");
  assert.doesNotMatch(limited.help, /額度不足|用完/);
  assert.equal(review.failurePresentation({ error_code: "PROVIDER_TIMEOUT" }).title, "辨識失敗");
});
