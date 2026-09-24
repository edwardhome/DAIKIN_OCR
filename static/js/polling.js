/* Keep the recognition view mounted while the server finishes its work. */
(function (window) {
  "use strict";

  function watch({
    load,
    onProgress = () => {},
    onComplete = () => {},
    onError = () => {},
    isPending,
    intervalMs = 1800,
  }) {
    if (typeof load !== "function" || typeof isPending !== "function")
      throw new TypeError("Polling requires load and isPending functions.");
    if (!Number.isFinite(intervalMs) || intervalMs <= 0)
      throw new TypeError("Polling interval must be a positive number.");

    let stopped = false;
    let timer = null;
    let controller = null;
    let failures = 0;

    function stop() {
      if (stopped) return;
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      if (controller) controller.abort();
      controller = null;
    }

    function schedule(delay) {
      if (!stopped) timer = window.setTimeout(tick, delay);
    }

    async function tick() {
      timer = null;
      if (stopped) return;
      controller = new window.AbortController();
      let job;
      let pending;
      try {
        job = await load(controller.signal);
        if (stopped) return;
        pending = isPending(job);
      } catch (error) {
        if (stopped) return;
        failures = Math.min(failures + 1, 2);
        try {
          onError(error);
        } finally {
          schedule(intervalMs * 2 ** failures);
        }
        return;
      } finally {
        controller = null;
      }

      if (stopped) return;
      failures = 0;
      if (pending) {
        try {
          onProgress(job);
        } finally {
          schedule(intervalMs);
        }
      } else {
        // End this watcher before notifying the UI, so completion is one-shot.
        stop();
        onComplete(job);
      }
    }

    // The caller already has the initial job; do not immediately fetch it again.
    schedule(intervalMs);
    return stop;
  }

  window.NameplatePolling = Object.freeze({ watch });
})(window);
