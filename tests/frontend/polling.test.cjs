const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../static/js/polling.js"),
  "utf8",
);

function setup() {
  let nextId = 0;
  let now = 0;
  const timers = new Map();
  const window = {
    AbortController,
    setTimeout(callback, delay) {
      const id = ++nextId;
      timers.set(id, { callback, due: now + delay });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };
  vm.runInNewContext(source, { window });
  function fireNext() {
    const next = [...timers].sort((a, b) => a[1].due - b[1].due)[0];
    assert.ok(next, "a poll should be scheduled");
    const [id, timer] = next;
    timers.delete(id);
    now = timer.due;
    timer.callback();
  }
  return {
    watch: window.NameplatePolling.watch,
    timers,
    fireNext,
    async poll() {
      fireNext();
      await flush();
    },
    nextDelay() {
      return Math.min(...[...timers.values()].map((timer) => timer.due - now));
    },
  };
}

async function flush() {
  for (let i = 0; i < 6; i++) await Promise.resolve();
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const isPending = (job) => job.status === "RUNNING";

test("pending jobs update progress without completing or reloading immediately", async () => {
  const clock = setup();
  let loads = 0;
  const progress = [];
  const completed = [];
  const stop = clock.watch({
    load: async () => ({ status: "RUNNING", sequence: ++loads }),
    isPending,
    onProgress: (job) => progress.push(job.sequence),
    onComplete: (job) => completed.push(job),
  });
  assert.equal(loads, 0);
  assert.equal(clock.nextDelay(), 1800);
  await clock.poll();
  await clock.poll();
  assert.deepEqual(progress, [1, 2]);
  assert.equal(completed.length, 0);
  assert.equal(clock.timers.size, 1);
  stop();
});

test("completion notifies exactly once and schedules no further requests", async () => {
  const clock = setup();
  const completed = [];
  const stop = clock.watch({
    load: async () => ({ status: "SUCCEEDED" }),
    isPending,
    onComplete: (job) => completed.push(job),
  });
  await clock.poll();
  assert.equal(completed.length, 1);
  assert.equal(clock.timers.size, 0);
  stop();
  stop();
  assert.equal(completed.length, 1);
});

test("network errors back off to a bounded delay and recover without completion", async () => {
  const clock = setup();
  let loads = 0;
  let errors = 0;
  let progress = 0;
  let completed = 0;
  const stop = clock.watch({
    load: async () => {
      if (++loads <= 3) throw new Error("temporary connection failure");
      return { status: "RUNNING" };
    },
    isPending,
    onError: () => errors++,
    onProgress: () => progress++,
    onComplete: () => completed++,
    intervalMs: 100,
  });
  await clock.poll();
  assert.equal(clock.nextDelay(), 200);
  await clock.poll();
  assert.equal(clock.nextDelay(), 400);
  await clock.poll();
  assert.equal(clock.nextDelay(), 400);
  await clock.poll();
  assert.equal(clock.nextDelay(), 100);
  assert.equal(errors, 3);
  assert.equal(progress, 1);
  assert.equal(completed, 0);
  stop();
});

test("stopping aborts an in-flight request and ignores a late response", async () => {
  const clock = setup();
  const request = deferred();
  let signal;
  let callbacks = 0;
  const stop = clock.watch({
    load: (requestSignal) => {
      signal = requestSignal;
      return request.promise;
    },
    isPending,
    onProgress: () => callbacks++,
    onComplete: () => callbacks++,
    onError: () => callbacks++,
  });
  clock.fireNext();
  assert.equal(signal.aborted, false);
  stop();
  assert.equal(signal.aborted, true);
  request.resolve({ status: "SUCCEEDED" });
  await flush();
  assert.equal(callbacks, 0);
  assert.equal(clock.timers.size, 0);
});

test("stopping ignores a late request rejection and clears an idle timer", async () => {
  const clock = setup();
  const request = deferred();
  let errors = 0;
  const stop = clock.watch({
    load: () => request.promise,
    isPending,
    onError: () => errors++,
  });
  clock.fireNext();
  stop();
  request.reject(new Error("aborted"));
  await flush();
  assert.equal(errors, 0);
  assert.equal(clock.timers.size, 0);

  const stopIdle = clock.watch({ load: () => request.promise, isPending });
  assert.equal(clock.timers.size, 1);
  stopIdle();
  assert.equal(clock.timers.size, 0);
});

test("a slow request cannot overlap another poll", async () => {
  const clock = setup();
  const request = deferred();
  let loads = 0;
  const stop = clock.watch({
    load: () => {
      loads++;
      return request.promise;
    },
    isPending,
  });
  clock.fireNext();
  await flush();
  assert.equal(loads, 1);
  assert.equal(clock.timers.size, 0);
  request.resolve({ status: "RUNNING" });
  await flush();
  assert.equal(clock.timers.size, 1);
  assert.equal(clock.nextDelay(), 1800);
  stop();
});
