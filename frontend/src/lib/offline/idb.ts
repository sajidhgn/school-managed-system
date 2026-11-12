/**
 * A minimal key-value store on IndexedDB, for offline mode.
 *
 * IndexedDB rather than localStorage: a saved student directory and a few rosters
 * can pass localStorage's ~5 MB, and localStorage blocks the main thread on every
 * write. No library: offline mode needs get / set / delete / list, and those are a
 * page of code.
 *
 * Everything degrades to "nothing stored" when IndexedDB is unavailable (some
 * private windows): the app then simply has no offline copy, it does not break.
 */

const DB_NAME = "schoolyar-offline";
const STORE = "kv";
const VERSION = 1;

let dbPromise: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB unavailable"));
      return;
    }
    const request = indexedDB.open(DB_NAME, VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  // A failed open must not poison every later call.
  dbPromise.catch(() => {
    dbPromise = null;
  });
  return dbPromise;
}

function run<T>(
  mode: IDBTransactionMode,
  body: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(STORE, mode);
        const request = body(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(request.result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      }),
  );
}

export async function idbGet<T>(key: string): Promise<T | undefined> {
  try {
    return (await run("readonly", (store) => store.get(key))) as T | undefined;
  } catch {
    return undefined;
  }
}

export async function idbSet(key: string, value: unknown): Promise<void> {
  try {
    await run("readwrite", (store) => store.put(value, key));
  } catch {
    // No storage: nothing is kept offline. Reads will find nothing either.
  }
}

export async function idbDelete(key: string): Promise<void> {
  try {
    await run("readwrite", (store) => store.delete(key));
  } catch {
    // Nothing to delete.
  }
}

export async function idbKeys(): Promise<string[]> {
  try {
    return ((await run("readonly", (store) => store.getAllKeys())) as IDBValidKey[]).map(String);
  } catch {
    return [];
  }
}
