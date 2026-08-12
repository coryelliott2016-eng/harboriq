/**
 * A tiny, dependency-free IndexedDB wrapper for the field app's offline
 * cache and outbox (Phase 12), with at-rest encryption (marine threat model
 * Scenario 1, 2026-08-11).
 *
 * Deliberately NOT using the `idb` package: two object stores, four
 * operations (get/getAll/put/delete), and a small schema is little enough
 * that a raw `indexedDB` wrapper keeps one fewer dependency without
 * meaningfully increasing the code here.
 *
 * Object stores:
 *  - `cached_jobs`     — the technician's most recent successfully fetched
 *                        job list, written on every successful fetch and
 *                        read back when offline (see useFieldJobs.ts).
 *                        Values are AES-GCM envelopes (see offlineVault.ts).
 *  - `pending_actions` — the offline-sync outbox. Values are AES-GCM
 *                        envelopes; the IDB keyPath remains the plaintext
 *                        idempotency key so deletes/replays stay O(1).
 *  - `vault_meta`      — device encryption key material (DEK).
 *
 * Schema v2 wiped any pre-encryption plaintext rows on upgrade — better to
 * re-fetch jobs than leave customer PII readable on disk.
 */

import {
  VAULT_DEK_KEY,
  VAULT_META_STORE,
  cacheDek,
  clearCachedDek,
  decryptJson,
  encryptJson,
  exportDekRaw,
  generateDek,
  getCachedDek,
  importDekRaw,
  isEncryptedEnvelope,
  _resetVaultCacheForTests,
  type EncryptedEnvelope,
} from "./offlineVault";

const DB_NAME = "harboriq-field";
/** v1 = plaintext stores. v2 = encrypted envelopes + vault_meta. */
const DB_VERSION = 2;
export const CACHED_JOBS_STORE = "cached_jobs";
export const PENDING_ACTIONS_STORE = "pending_actions";

/** Stores whose entire value is an encrypted envelope (key kept in keyPath). */
const ENCRYPTED_STORES = new Set([CACHED_JOBS_STORE, PENDING_ACTIONS_STORE]);

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB is not available in this environment"));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      const oldVersion = event.oldVersion;

      // Fresh install or upgrade from plaintext v1: ensure stores exist and
      // drop any pre-encryption rows so we never leave customer PII on disk.
      if (!db.objectStoreNames.contains(CACHED_JOBS_STORE)) {
        db.createObjectStore(CACHED_JOBS_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(PENDING_ACTIONS_STORE)) {
        db.createObjectStore(PENDING_ACTIONS_STORE, { keyPath: "idempotencyKey" });
      }
      if (!db.objectStoreNames.contains(VAULT_META_STORE)) {
        db.createObjectStore(VAULT_META_STORE, { keyPath: "id" });
      }

      if (oldVersion > 0 && oldVersion < 2) {
        // Clear plaintext legacy data inside the upgrade transaction.
        const tx = request.transaction;
        if (tx) {
          if (db.objectStoreNames.contains(CACHED_JOBS_STORE)) {
            tx.objectStore(CACHED_JOBS_STORE).clear();
          }
          if (db.objectStoreNames.contains(PENDING_ACTIONS_STORE)) {
            tx.objectStore(PENDING_ACTIONS_STORE).clear();
          }
        }
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

async function withStore<T>(
  storeName: string,
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T> | IDBRequest<T>[] | void,
): Promise<T | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    let result: T | undefined;
    const req = fn(store);
    if (req && !Array.isArray(req)) {
      req.onsuccess = () => {
        result = req.result;
      };
      req.onerror = () => reject(req.error);
    }
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

async function ensureDek(): Promise<CryptoKey> {
  const cached = getCachedDek();
  if (cached) return cached;

  const existing = await withStore<{ id: string; raw: string }>(
    VAULT_META_STORE,
    "readonly",
    (store) => store.get(VAULT_DEK_KEY),
  );
  if (existing?.raw) {
    const key = await importDekRaw(existing.raw);
    cacheDek(key);
    return key;
  }

  const key = await generateDek();
  const raw = await exportDekRaw(key);
  await withStore(VAULT_META_STORE, "readwrite", (store) => {
    store.put({ id: VAULT_DEK_KEY, raw });
  });
  cacheDek(key);
  return key;
}

/**
 * Wrap a plain application object for encrypted storage.
 *
 * For `pending_actions` the IDB keyPath is `idempotencyKey` and must remain
 * a top-level plaintext field so `delete(key)` keeps working. For
 * `cached_jobs` the keyPath is `id`. Everything else lives inside the
 * ciphertext so DevTools / bulk dumps do not show customer fields.
 */
async function sealForStore(storeName: string, item: Record<string, unknown>): Promise<Record<string, unknown>> {
  const key = await ensureDek();
  if (storeName === PENDING_ACTIONS_STORE) {
    const idempotencyKey = item.idempotencyKey;
    if (typeof idempotencyKey !== "string") {
      throw new Error("pending_actions item missing idempotencyKey");
    }
    const { idempotencyKey: _k, ...rest } = item;
    const envelope = await encryptJson(key, rest);
    return { idempotencyKey, ...envelope };
  }
  if (storeName === CACHED_JOBS_STORE) {
    const id = item.id;
    if (typeof id !== "string") {
      throw new Error("cached_jobs item missing id");
    }
    const { id: _id, ...rest } = item;
    const envelope = await encryptJson(key, { id, ...rest });
    // Keep plaintext id for keyPath; full job (including id) is also inside ct
    // so decrypt restores a complete Job object.
    return { id, ...envelope };
  }
  return item;
}

async function openSealed<T>(storeName: string, row: unknown): Promise<T | null> {
  if (row == null) return null;
  if (!ENCRYPTED_STORES.has(storeName)) return row as T;

  const record = row as Record<string, unknown>;
  // Legacy plaintext row (should not exist after v2 upgrade clear) — skip.
  if (!isEncryptedEnvelope(record)) {
    return null;
  }

  const key = await ensureDek();
  const envelope: EncryptedEnvelope = { v: 1, iv: record.iv as string, ct: record.ct as string };

  if (storeName === PENDING_ACTIONS_STORE) {
    const body = await decryptJson<Record<string, unknown>>(key, envelope);
    return { idempotencyKey: record.idempotencyKey, ...body } as T;
  }
  // cached_jobs: full object is inside the envelope.
  return decryptJson<T>(key, envelope);
}

export async function putAll<T>(storeName: string, items: T[]): Promise<void> {
  const db = await openDb();
  // Ensure DEK exists before the write transaction (WebCrypto is async and
  // must not run inside an IDB transaction callback).
  if (ENCRYPTED_STORES.has(storeName)) {
    await ensureDek();
  }
  const sealed: Record<string, unknown>[] = [];
  for (const item of items) {
    if (ENCRYPTED_STORES.has(storeName)) {
      sealed.push(await sealForStore(storeName, item as Record<string, unknown>));
    } else {
      sealed.push(item as Record<string, unknown>);
    }
  }
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    const store = tx.objectStore(storeName);
    store.clear();
    for (const row of sealed) store.put(row);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export async function put<T>(storeName: string, item: T): Promise<void> {
  let toStore: unknown = item;
  if (ENCRYPTED_STORES.has(storeName)) {
    toStore = await sealForStore(storeName, item as Record<string, unknown>);
  }
  await withStore(storeName, "readwrite", (store) => {
    store.put(toStore);
  });
}

export async function getAllItems<T>(storeName: string): Promise<T[]> {
  const result = await withStore<unknown[]>(storeName, "readonly", (store) => store.getAll());
  const rows = result ?? [];
  if (!ENCRYPTED_STORES.has(storeName)) {
    return rows as T[];
  }
  const out: T[] = [];
  for (const row of rows) {
    try {
      const opened = await openSealed<T>(storeName, row);
      if (opened != null) out.push(opened);
    } catch {
      // Tampered / undecryptable row — skip rather than failing the whole
      // offline load. Drift/monitor can catch empty caches.
    }
  }
  return out;
}

export async function deleteItem(storeName: string, key: string): Promise<void> {
  await withStore(storeName, "readwrite", (store) => {
    store.delete(key);
  });
}

/**
 * Local wipe of the field offline vault (threat model Scenario 1 stopgap /
 * logout hygiene). Clears cached jobs, pending actions, and the DEK so
 * residual ciphertext on this profile is no longer decryptable.
 *
 * Safe to call when IndexedDB is unavailable — failures are swallowed so
 * logout always completes.
 */
export async function wipeFieldOfflineData(): Promise<void> {
  clearCachedDek();
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(
        [CACHED_JOBS_STORE, PENDING_ACTIONS_STORE, VAULT_META_STORE],
        "readwrite",
      );
      tx.objectStore(CACHED_JOBS_STORE).clear();
      tx.objectStore(PENDING_ACTIONS_STORE).clear();
      tx.objectStore(VAULT_META_STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } catch {
    /* logout must not fail because IndexedDB is flaky */
  } finally {
    clearCachedDek();
  }
}

/** Test/dev helper: drop and recreate the whole database. Closes the
 * currently-open connection first -- `indexedDB.deleteDatabase` otherwise
 * blocks forever waiting for every open connection to close, which never
 * happens on its own within a single test process. */
export async function _resetForTests(): Promise<void> {
  _resetVaultCacheForTests();
  clearCachedDek();
  if (dbPromise) {
    try {
      const db = await dbPromise;
      db.close();
    } catch {
      /* ignore -- nothing to close */
    }
  }
  dbPromise = null;
  await new Promise<void>((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
    req.onblocked = () => resolve();
  });
}
