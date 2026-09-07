import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  enqueueAction,
  listQueuedActions,
  MAX_QUEUE_AGE_MS,
  newIdempotencyKey,
  purgeStaleQueuedActions,
  removeQueuedAction,
  replayQueue,
  type ActionSender,
  type PendingAction,
} from "./offlineQueue";
import { _resetForTests } from "./offlineDb";

/**
 * Offline queue logic tests (Phase 12) -- per the spec, the highest-value
 * tests in this phase. Exercises enqueue/replay/ordering/idempotency
 * end-to-end against a real (fake) IndexedDB, with a mocked network
 * "sender" standing in for navigator.onLine / fetch failures.
 */
describe("offlineQueue", () => {
  beforeEach(async () => {
    await _resetForTests();
  });

  it("starts empty", async () => {
    expect(await listQueuedActions()).toEqual([]);
  });

  it("enqueues an action and can list it back out", async () => {
    const key = newIdempotencyKey();
    await enqueueAction({
      idempotencyKey: key,
      kind: "clock_in",
      jobId: "job-1",
      payload: {},
    });

    const queued = await listQueuedActions();
    expect(queued).toHaveLength(1);
    expect(queued[0].idempotencyKey).toBe(key);
    expect(queued[0].kind).toBe("clock_in");
    expect(queued[0].jobId).toBe("job-1");
    expect(queued[0].attempts).toBe(0);
  });

  it("removes an action from the queue by idempotency key", async () => {
    const key = newIdempotencyKey();
    await enqueueAction({ idempotencyKey: key, kind: "clock_out", jobId: "job-1", payload: {} });
    expect(await listQueuedActions()).toHaveLength(1);

    await removeQueuedAction(key);
    expect(await listQueuedActions()).toHaveLength(0);
  });

  it("replays a queued action and removes it on success (simulating reconnect)", async () => {
    const key = newIdempotencyKey();
    await enqueueAction({ idempotencyKey: key, kind: "clock_in", jobId: "job-1", payload: {} });

    const send: ActionSender = vi.fn(async () => {
      /* simulate a successful network call once "back online" */
    });

    const result = await replayQueue(send);

    expect(send).toHaveBeenCalledTimes(1);
    expect(result.succeeded).toEqual([key]);
    expect(result.failed).toEqual([]);
    expect(await listQueuedActions()).toEqual([]);
  });

  it("keeps a failed action queued and increments its attempt count (simulating still-offline)", async () => {
    const key = newIdempotencyKey();
    await enqueueAction({ idempotencyKey: key, kind: "clock_in", jobId: "job-1", payload: {} });

    const send: ActionSender = vi.fn(async () => {
      throw new Error("network request failed"); // simulated navigator.onLine === false / fetch failure
    });

    const result = await replayQueue(send);

    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([key]);

    const stillQueued = await listQueuedActions();
    expect(stillQueued).toHaveLength(1);
    expect(stillQueued[0].attempts).toBe(1);
    expect(stillQueued[0].lastError).toContain("network request failed");
  });

  it("replays multiple queued actions in the order they were enqueued", async () => {
    const calls: string[] = [];
    const keys: string[] = [];

    for (const kind of ["clock_in", "attachment", "clock_out"] as const) {
      const key = newIdempotencyKey();
      keys.push(key);
      await enqueueAction({ idempotencyKey: key, kind, jobId: "job-1", payload: {} });
      // Ensure strictly increasing createdAt so ordering is unambiguous
      // even if the clock resolution is coarse in the test environment.
      await new Promise((resolve) => setTimeout(resolve, 2));
    }

    const send: ActionSender = vi.fn(async (action: PendingAction) => {
      calls.push(action.idempotencyKey);
    });

    const result = await replayQueue(send);

    expect(calls).toEqual(keys);
    expect(result.succeeded).toEqual(keys);
    expect(await listQueuedActions()).toEqual([]);
  });

  it("stops replaying at the first failure so a later action never jumps ahead (in-order delivery)", async () => {
    const keyA = newIdempotencyKey();
    const keyB = newIdempotencyKey();
    await enqueueAction({ idempotencyKey: keyA, kind: "clock_in", jobId: "job-1", payload: {} });
    await new Promise((resolve) => setTimeout(resolve, 2));
    await enqueueAction({ idempotencyKey: keyB, kind: "clock_out", jobId: "job-1", payload: {} });

    const attempted: string[] = [];
    const send: ActionSender = vi.fn(async (action: PendingAction) => {
      attempted.push(action.idempotencyKey);
      if (action.idempotencyKey === keyA) {
        throw new Error("still offline");
      }
    });

    const result = await replayQueue(send);

    // Only the first (oldest) action was even attempted -- clock_out never
    // got a chance to run ahead of the still-failing clock_in.
    expect(attempted).toEqual([keyA]);
    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([keyA]);

    const stillQueued = await listQueuedActions();
    expect(stillQueued.map((a) => a.idempotencyKey)).toEqual([keyA, keyB]);
  });

  it("is idempotent under a duplicate replay of an action the server already accepted", async () => {
    // Simulates: request succeeded server-side, but the response was lost
    // (e.g. connection dropped) so the client still thinks it needs to
    // retry. The *server* is responsible for the actual dedup (unique
    // idempotency-key index) -- this test documents that the client simply
    // resends the same key both times without minting a new one.
    const key = newIdempotencyKey();
    const seenKeys: string[] = [];
    let callCount = 0;

    const send: ActionSender = vi.fn(async (action: PendingAction) => {
      callCount += 1;
      seenKeys.push(action.idempotencyKey);
      if (callCount === 1) {
        throw new Error("response lost after server processed the request");
      }
      // Second attempt "succeeds" (server recognizes the same idempotency
      // key from attempt 1 and returns the original row, per
      // app/services/field_app.py).
    });

    await enqueueAction({ idempotencyKey: key, kind: "clock_in", jobId: "job-1", payload: {} });
    const first = await replayQueue(send);
    expect(first.failed).toEqual([key]);

    const second = await replayQueue(send);
    expect(second.succeeded).toEqual([key]);

    expect(seenKeys).toEqual([key, key]);
    expect(await listQueuedActions()).toEqual([]);
  });

  it("mints unique idempotency keys", () => {
    const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(50);
  });
});

describe("offline queue age limits (threat model S1/S3)", () => {
  beforeEach(async () => {
    await _resetForTests();
  });

  it("purgeStaleQueuedActions drops items older than MAX_QUEUE_AGE_MS", async () => {
    const freshKey = newIdempotencyKey();
    const staleKey = newIdempotencyKey();
    const now = Date.now();
    await enqueueAction({
      idempotencyKey: freshKey,
      kind: "clock_in",
      jobId: "job-1",
      payload: {},
      createdAt: new Date(now).toISOString(),
    });
    await enqueueAction({
      idempotencyKey: staleKey,
      kind: "clock_out",
      jobId: "job-1",
      payload: {},
      createdAt: new Date(now - MAX_QUEUE_AGE_MS - 60_000).toISOString(),
    });

    const removed = await purgeStaleQueuedActions(now);
    expect(removed).toBe(1);
    const remaining = await listQueuedActions();
    expect(remaining.map((a) => a.idempotencyKey)).toEqual([freshKey]);
  });

  it("replayQueue purges stale items before sending", async () => {
    const staleKey = newIdempotencyKey();
    const nowIso = new Date(Date.now() - MAX_QUEUE_AGE_MS - 1).toISOString();
    await enqueueAction({
      idempotencyKey: staleKey,
      kind: "clock_in",
      jobId: "job-1",
      payload: {},
      createdAt: nowIso,
    });
    const sent: string[] = [];
    const result = await replayQueue(async (action) => {
      sent.push(action.idempotencyKey);
    });
    expect(sent).toEqual([]);
    expect(result.succeeded).toEqual([]);
    expect(await listQueuedActions()).toEqual([]);
  });
});
