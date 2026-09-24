"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { runInNewContext } = require("node:vm");
const { File } = require("node:buffer");

const source = readFileSync(
  join(__dirname, "../../static/js/sharing.js"),
  "utf8",
);

function load(overrides = {}) {
  const context = {
    navigator: {},
    document: {},
    location: {
      origin: "http://100.100.223.93:50003",
      href: "http://100.100.223.93:50003/jobs/abc",
    },
    URL,
    File,
    ...overrides,
  };
  context.document = {
    createElement: () => textarea(),
    body: { append() {} },
    ...overrides.document,
  };
  runInNewContext(source, context);
  return context.NameplateSharing;
}

function textarea() {
  return {
    value: "",
    focused: false,
    selected: false,
    setAttribute() {},
    remove() {},
    focus() {
      this.focused = true;
    },
    select() {
      this.selected = true;
    },
    setSelectionRange(start, end) {
      this.selection = [start, end];
    },
  };
}

test("HTTP copy executes before returning and reports the command's true success", async () => {
  const field = textarea();
  let called = false;
  const sharing = load({
    document: {
      execCommand(command) {
        called = true;
        assert.equal(command, "copy");
        assert.equal(field.value, "銘牌\nRHF50RVLT");
        return true;
      },
    },
  });
  const pending = sharing.copyText("銘牌\nRHF50RVLT", field);
  assert.equal(called, true);
  const result = await pending;
  assert.equal(result.copied, true);
  assert.equal(result.method, "execCommand");
});

test("copy uses and removes its own buffer when the caller textarea is hidden or omitted", async () => {
  const hiddenField = textarea();
  hiddenField.getClientRects = () => [];
  hiddenField.select = () => {
    throw new Error("hidden textarea cannot be selected");
  };
  let buffer;
  let removed = false;
  const sharing = load({
    document: {
      createElement() {
        buffer = textarea();
        buffer.remove = () => {
          removed = true;
        };
        return buffer;
      },
      execCommand() {
        assert.notEqual(buffer, hiddenField);
        assert.equal(buffer.selected, true);
        assert.equal(buffer.value, "已确认");
        return true;
      },
    },
  });
  assert.equal((await sharing.copyText("已确认", hiddenField)).copied, true);
  assert.equal(hiddenField.selected, false);
  assert.equal(removed, true);
  assert.equal((await sharing.copyText("已确认")).copied, true);
});

test("copy permission rejection leaves selected text and never claims success", async () => {
  const order = [];
  const sharing = load({
    document: {
      execCommand() {
        order.push("legacy");
        return false;
      },
    },
    navigator: {
      clipboard: {
        writeText() {
          order.push("clipboard");
          return Promise.reject(new Error("denied"));
        },
      },
    },
  });
  const field = textarea();
  const result = await sharing.copyText("資料", field);
  assert.deepEqual(order, ["legacy", "clipboard"]);
  assert.equal(result.copied, false);
  assert.equal(result.method, "manual");
  assert.equal(result.selected, true);
  assert.deepEqual(field.selection, [0, 2]);
});

test("modern clipboard can succeed when the legacy command is disabled", async () => {
  let copied;
  const sharing = load({
    navigator: {
      clipboard: {
        writeText(value) {
          copied = value;
          return Promise.resolve();
        },
      },
    },
  });
  const result = await sharing.copyText("confirmed", textarea());
  assert.equal(copied, "confirmed");
  assert.equal(result.copied, true);
  assert.equal(result.method, "clipboard");
});

test("original HEIC bytes and MIME survive fetching and filename completion", async () => {
  const bytes = new Uint8Array([0, 1, 2, 255, 16, 0, 4]);
  let request;
  const revoked = [];
  class ObjectURL extends URL {
    static createObjectURL() {
      return "blob:test-original";
    }
    static revokeObjectURL(value) {
      revoked.push(value);
    }
  }
  const sharing = load({
    URL: ObjectURL,
    fetch: async (url, options) => {
      request = { url, options };
      return new Response(bytes, {
        headers: {
          "content-type": "image/heic",
          "content-disposition": "inline; filename=original.heic",
        },
      });
    },
  });
  const prepared = await sharing.prepareOriginal({
    url: "/api/jobs/abc/image",
    filename: "nameplate-abc",
  });
  assert.equal(prepared.filename, "nameplate-abc.heic");
  assert.equal(prepared.file.type, "image/heic");
  assert.deepEqual(new Uint8Array(await prepared.file.arrayBuffer()), bytes);
  assert.equal(request.options.credentials, "same-origin");
  assert.equal(request.options.redirect, "error");
  assert.equal(request.url, "http://100.100.223.93:50003/api/jobs/abc/image");
  sharing.releaseOriginal(prepared);
  sharing.releaseOriginal(prepared);
  assert.deepEqual(revoked, ["blob:test-original"]);
});

test("encoded Content-Disposition supplies a safe JPEG filename", async () => {
  const sharing = load({
    fetch: async () =>
      new Response("original", {
        headers: {
          "content-type": "image/jpeg",
          "content-disposition":
            "inline; filename*=UTF-8''%E9%8A%98%E7%89%8C.jpg",
        },
      }),
  });
  const prepared = await sharing.prepareOriginal({
    url: "/api/jobs/abc/image",
  });
  assert.equal(prepared.filename, "銘牌.jpg");
  sharing.releaseOriginal(prepared);
});

test("login responses and cross-origin resources cannot be shared as photos", async () => {
  let called = 0;
  const sharing = load({
    fetch: async () => {
      called++;
      return new Response("<html>login</html>", {
        headers: { "content-type": "text/html" },
      });
    },
  });
  await assert.rejects(
    sharing.prepareOriginal({ url: "http://elsewhere.test/image.jpg" }),
    /目前的辨識系統/,
  );
  assert.equal(called, 0);
  await assert.rejects(
    sharing.prepareOriginal({ url: "/api/jobs/abc/image" }),
    /未取得可分享的原始照片/,
  );
});

test("native share runs synchronously with the original file and confirmed text", async () => {
  const file = new File(["original"], "plate.jpg", { type: "image/jpeg" });
  let payload;
  const sharing = load({
    navigator: {
      canShare(data) {
        return data.files[0] === file;
      },
      share(data) {
        payload = data;
        return Promise.resolve();
      },
    },
  });
  const pending = sharing.shareConfirmed({ file, text: "已人工確認的資料" });
  assert.equal(payload.files[0], file);
  assert.equal(payload.text, "已人工確認的資料");
  assert.equal((await pending).status, "shared");
});

test("unsupported file sharing does not silently share only text", async () => {
  let calls = 0;
  const sharing = load({
    navigator: {
      canShare() {
        return false;
      },
      share() {
        calls++;
      },
    },
  });
  const result = await sharing.shareConfirmed({
    file: new File(["x"], "plate.heic"),
    text: "資料",
  });
  assert.equal(result.status, "unsupported");
  assert.equal(calls, 0);
});

test("native cancellation and permission failure return distinct outcomes", async () => {
  const file = new File(["x"], "plate.jpg");
  for (const [name, expected] of [
    ["AbortError", "cancelled"],
    ["NotAllowedError", "failed"],
  ]) {
    const sharing = load({
      navigator: {
        canShare() {
          return true;
        },
        share() {
          return Promise.reject(
            Object.assign(new Error("share failed"), { name }),
          );
        },
      },
    });
    assert.equal(
      (await sharing.shareConfirmed({ file, text: "資料" })).status,
      expected,
    );
  }
});

test("LINE text link preserves Chinese, newlines and URL-reserved characters", () => {
  const sharing = load();
  const value = "【資料】\n型號：A&B #1+2?";
  const url = new URL(sharing.lineTextUrl(value));
  assert.equal(url.origin, "https://line.me");
  assert.equal(url.pathname, "/R/share");
  assert.equal(url.searchParams.get("text"), value);
});
