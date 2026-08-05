/**
 * A tiny, dependency-free IndexedDB wrapper for the field app's offline
 * cache and outbox (Phase 12).
 *
 * Deliberately NOT using the `idb` package: two object stores, four
 * operations (get/getAll/put/delete), and a version-1 schema is little
 * enough that a raw `indexedDB` wrapper keeps one fewer dependency without
 * meaningfully increasing the code here.
 *
 * Two object stores:
 *  - `cached_jobs`     — the technician's most recent successfully fetched
 *                        job list, written on every successful fetch and
 *                        read back when offline (see useFieldJobs.ts).
 *  - `pending_actions` — the offline-sync outbox: field actions (status
 *                        change, note, photo, signature, clock in/out)
 *                        recorded while offline or after a failed request,
 *                        replayed in order once connectivity returns (see
 *                        offlineQueue.ts).
 */

const DB_NAME = "harboriq-field";
const DB_VERSION = 1;
export const CACHED_JOBS_STORE = "cached_jobs";
export const PENDING_ACTIONS_STORE = "pending_actions";

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB is not available in this environment"));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(CACHED_JOBS_STORE)) {
        db.createObjectStore(CACHED_JOBS_STORE, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(PENDING_ACTIONS_STORE)) {
        db.createObjectStore(PENDING_ACTIONS_STORE, { keyPath: "idempotencyKey" });
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

export async function putAll<T>(storeName: string, items: T[]): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    const store = tx.objectStore(storeName);
    store.clear();
    for (const item of items) store.put(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export async function put<T>(storeName: string, item: T): Promise<void> {
  await withStore<T>(storeName, "readwrite", (store) => {
    store.put(item);
  });
}

export async function getAllItems<T>(storeName: string): Promise<T[]> {
  const result = await withStore<T[]>(storeName, "readonly", (store) => store.getAll());
  return result ?? [];
}

export async function deleteItem(storeName: string, key: string): Promise<void> {
  await withStore(storeName, "readwrite", (store) => {
    store.delete(key);
  });
}

/** Test/dev helper: drop and recreate the whole database. Closes the
 * currently-open connection first -- `indexedDB.deleteDatabase` otherwise
 * blocks forever waiting for every open connection to close, which never
 * happens on its own within a single test process. */
export async function _resetForTests(): Promise<void> {
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
