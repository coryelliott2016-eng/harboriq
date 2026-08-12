import { beforeEach, describe, expect, it } from "vitest";
import {
  decryptJson,
  encryptJson,
  generateDek,
  isEncryptedEnvelope,
  _resetVaultCacheForTests,
} from "./offlineVault";
import { _resetForTests, put, getAllItems, PENDING_ACTIONS_STORE, CACHED_JOBS_STORE, wipeFieldOfflineData } from "./offlineDb";

describe("offlineVault AES-GCM", () => {
  beforeEach(async () => {
    _resetVaultCacheForTests();
    await _resetForTests();
  });

  it("round-trips JSON through AES-GCM", async () => {
    const key = await generateDek();
    const payload = { name: "Sea Breeze", slip: "A-12", notes: "customer PII" };
    const env = await encryptJson(key, payload);
    expect(isEncryptedEnvelope(env)).toBe(true);
    expect(env.ct).not.toContain("Sea Breeze");
    const opened = await decryptJson<typeof payload>(key, env);
    expect(opened).toEqual(payload);
  });

  it("fails closed on tampered ciphertext", async () => {
    const key = await generateDek();
    const env = await encryptJson(key, { secret: true });
    const tampered = { ...env, ct: env.ct.slice(0, -4) + "AAAA" };
    await expect(decryptJson(key, tampered)).rejects.toThrow(/decrypt failed/);
  });
});

describe("offlineDb encrypted stores", () => {
  beforeEach(async () => {
    _resetVaultCacheForTests();
    await _resetForTests();
  });

  it("stores pending_actions as envelopes (not plaintext PII)", async () => {
    await put(PENDING_ACTIONS_STORE, {
      idempotencyKey: "k1",
      kind: "clock_in",
      jobId: "job-1",
      payload: { note: "customer-secret" },
      createdAt: new Date().toISOString(),
      attempts: 0,
    });

    // Raw IDB read should not expose the payload plaintext.
    // Close this inspection connection when done — leaving it open blocks
    // indexedDB.deleteDatabase in subsequent _resetForTests calls.
    const raw = await new Promise<unknown[]>((resolve, reject) => {
      const req = indexedDB.open("harboriq-field", 2);
      req.onsuccess = () => {
        const db = req.result;
        const tx = db.transaction("pending_actions", "readonly");
        const getAll = tx.objectStore("pending_actions").getAll();
        getAll.onsuccess = () => {
          const rows = getAll.result as unknown[];
          db.close();
          resolve(rows);
        };
        getAll.onerror = () => {
          db.close();
          reject(getAll.error);
        };
      };
      req.onerror = () => reject(req.error);
    });
    expect(raw).toHaveLength(1);
    const row = raw[0] as Record<string, unknown>;
    expect(row.v).toBe(1);
    expect(typeof row.ct).toBe("string");
    expect(JSON.stringify(row)).not.toContain("customer-secret");
    expect(row.idempotencyKey).toBe("k1");

    // Transparent API still returns the full action.
    const listed = await getAllItems<{ idempotencyKey: string; payload: { note: string } }>(
      PENDING_ACTIONS_STORE,
    );
    expect(listed).toHaveLength(1);
    expect(listed[0]!.payload.note).toBe("customer-secret");
  });

  it("stores cached_jobs encrypted and restores on read", async () => {
    await put(CACHED_JOBS_STORE, {
      id: "job-9",
      title: "Bottom paint",
      customer_name: "Alice Marina",
    });
    const jobs = await getAllItems<{ id: string; customer_name: string }>(CACHED_JOBS_STORE);
    expect(jobs).toEqual([
      { id: "job-9", title: "Bottom paint", customer_name: "Alice Marina" },
    ]);
  });

  it("wipeFieldOfflineData destroys decryptability", async () => {
    await put(PENDING_ACTIONS_STORE, {
      idempotencyKey: "k-wipe",
      kind: "clock_out",
      jobId: "job-1",
      payload: {},
      createdAt: new Date().toISOString(),
      attempts: 0,
    });
    expect(await getAllItems(PENDING_ACTIONS_STORE)).toHaveLength(1);
    await wipeFieldOfflineData();
    expect(await getAllItems(PENDING_ACTIONS_STORE)).toHaveLength(0);
  });
});
