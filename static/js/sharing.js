(function (global) {
  "use strict";

  const imageExtensions = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/heif": "heif",
  };
  const objectUrls = new Set();

  function dispositionFilename(header) {
    if (!header) return "";
    const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
    if (encoded) {
      try {
        return decodeURIComponent(encoded[1].trim());
      } catch {
        // Fall back to the ordinary filename when the encoded one is malformed.
      }
    }
    const ordinary = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(header);
    return (ordinary?.[1] || ordinary?.[2] || "").trim();
  }

  function imageFilename(preferred, disposition, mime) {
    const stem = String(
      preferred || dispositionFilename(disposition) || "nameplate-original",
    )
      .replace(/[\u0000-\u001f\u007f/\\]/g, "_")
      .replace(/\.(?:jpe?g|png|heic|heif)$/i, "")
      .trim()
      .slice(0, 180);
    return `${stem || "nameplate-original"}.${imageExtensions[mime]}`;
  }

  async function prepareOriginal({ url, filename, signal } = {}) {
    const source = new URL(url, global.location.href);
    if (
      source.origin !== global.location.origin ||
      !["http:", "https:"].includes(source.protocol)
    ) {
      throw new Error("原始照片必須從目前的辨識系統讀取。");
    }
    const response = await global.fetch(source.href, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...(signal ? { signal } : {}),
    });
    if (!response.ok) {
      throw new Error(
        response.status === 401
          ? "登入已過期，請重新登入後再分享原始照片。"
          : "原始照片讀取失敗，請重新載入頁面再試。",
      );
    }
    const mime = (response.headers.get("content-type") || "")
      .split(";")[0]
      .trim()
      .toLowerCase();
    if (!Object.hasOwn(imageExtensions, mime)) {
      throw new Error("未取得可分享的原始照片，請重新載入頁面再試。");
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error("原始照片是空白檔案，無法分享。");
    const name = imageFilename(
      filename,
      response.headers.get("content-disposition"),
      mime,
    );
    // Keep the original bytes, including HEIC/HEIF; do not re-encode a preview.
    const file =
      typeof global.File === "function"
        ? new global.File([blob], name, { type: mime })
        : null;
    const objectUrl = global.URL.createObjectURL(file || blob);
    objectUrls.add(objectUrl);
    return {
      file,
      url: objectUrl,
      sourceUrl: source.href,
      filename: name,
      mime,
      size: blob.size,
    };
  }

  function releaseOriginal(prepared) {
    if (prepared?.url && objectUrls.delete(prepared.url)) {
      global.URL.revokeObjectURL(prepared.url);
    }
  }

  function selectText(text, textarea) {
    if (!textarea) return false;
    textarea.value = text;
    if (textarea.getClientRects && !textarea.getClientRects().length)
      return false;
    try {
      textarea.focus({ preventScroll: true });
      textarea.select();
      textarea.setSelectionRange(0, text.length);
      return true;
    } catch {
      return false;
    }
  }

  function legacyCopy(text) {
    const previous = global.document.activeElement;
    let buffer;
    try {
      // The caller's textarea may live inside a closed details element. A short-
      // lived, selectable buffer makes copying independent of that layout.
      buffer = global.document.createElement("textarea");
      buffer.className = "clipboard-copy-buffer";
      buffer.readOnly = true;
      buffer.tabIndex = -1;
      buffer.rows = 1;
      buffer.setAttribute("aria-hidden", "true");
      global.document.body.append(buffer);
      if (!selectText(text, buffer)) return false;
      return global.document.execCommand?.("copy") === true;
    } catch {
      return false;
    } finally {
      buffer?.remove();
      try {
        previous?.focus({ preventScroll: true });
      } catch {
        // Restoring focus should not change the copy result.
      }
    }
  }

  // Do this synchronously in the click handler: HTTP browsers need the older
  // copy command, and awaiting a rejected clipboard promise can lose activation.
  function copyText(text, textarea) {
    text = String(text ?? "");
    if (textarea) textarea.value = text;
    if (legacyCopy(text)) {
      return Promise.resolve({
        copied: true,
        method: "execCommand",
        selected: false,
      });
    }
    const manual = () => ({
      copied: false,
      method: "manual",
      selected: selectText(text, textarea),
    });
    try {
      if (typeof global.navigator.clipboard?.writeText === "function") {
        return Promise.resolve(global.navigator.clipboard.writeText(text)).then(
          () => ({ copied: true, method: "clipboard", selected: false }),
          () => manual(),
        );
      }
    } catch {
      // Some browser permissions fail synchronously rather than rejecting.
    }
    return Promise.resolve(manual());
  }

  function canShareFiles(file) {
    if (
      !file ||
      typeof global.navigator.share !== "function" ||
      typeof global.navigator.canShare !== "function"
    ) {
      return false;
    }
    try {
      return global.navigator.canShare({ files: [file] }) === true;
    } catch {
      return false;
    }
  }

  function shareFailure(error) {
    return {
      status: error?.name === "AbortError" ? "cancelled" : "failed",
      error,
    };
  }

  // Call directly from a click after prepareOriginal has completed. Never fetch
  // here: navigator.share must run before the browser drops the user's gesture.
  function shareConfirmed({ file, text } = {}) {
    if (!canShareFiles(file)) return Promise.resolve({ status: "unsupported" });
    try {
      return Promise.resolve(
        global.navigator.share({
          files: [file],
          text: String(text ?? ""),
        }),
      ).then(() => ({ status: "shared" }), shareFailure);
    } catch (error) {
      return Promise.resolve(shareFailure(error));
    }
  }

  function lineTextUrl(text) {
    // The official LINE URL scheme accepts text, not local image attachments.
    return `https://line.me/R/share?text=${encodeURIComponent(String(text ?? ""))}`;
  }

  global.NameplateSharing = Object.freeze({
    prepareOriginal,
    releaseOriginal,
    copyText,
    canShareFiles,
    shareConfirmed,
    lineTextUrl,
  });
})(typeof window === "undefined" ? globalThis : window);
