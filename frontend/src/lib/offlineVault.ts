/**
 * Field-app offline vault (marine threat model Scenario 1, 2026-08-11).
 *
 * Encrypts IndexedDB payloads at rest with AES-GCM via WebCrypto so a lost
 * or stolen technician device does not expose customer PII, addresses,
 * signatures, or photos as readable JSON in DevTools / bulk IDB dumps.
 *
 * Design notes:
 *  - A per-browser device key (DEK) is generated once and stored in the
 *    `vault_meta` object store. The DEK is extractable only to this origin's
 *    script context — not a password-gated HSM, but a large step up from the
 *    previous plaintext stores. A later phase can wrap this DEK with a
 *    user-password or WebAuthn-bound wrapping key without changing callers.
 *  - `wipeVault()` deletes the DEK and is invoked on logout so a reported
 *    lost-device flow (revoke-all sessions + logout) also destroys local
 *    ciphertext readability on this browser profile.
 *  - Integrity: AES-GCM provides authenticated encryption; tampering with
 *    ciphertext fails closed on decrypt (Scenario 3 partial).
 */

const ALGO = "AES-GCM";
const KEY_LENGTH = 256;
const IV_BYTES = 12;

export const VAULT_META_STORE = "vault_meta";
export const VAULT_DEK_KEY = "dek";

/** Envelope written into IndexedDB instead of plaintext application objects. */
export interface EncryptedEnvelope {
  /** Discriminator so readers can reject leftover plaintext rows after upgrade. */
  v: 1;
  iv: string;
  ct: string;
}

function bytesToBase64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (let i = 0; i < view.length; i += 1) binary += String.fromCharCode(view[i]!);
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

function requireSubtle(): SubtleCrypto {
  if (typeof crypto === "undefined" || !crypto.subtle) {
    throw new Error("WebCrypto is not available — cannot open the offline vault");
  }
  return crypto.subtle;
}

let cachedDek: CryptoKey | null = null;

/** Test helper: drop the in-memory DEK cache (does not touch IndexedDB). */
export function _resetVaultCacheForTests(): void {
  cachedDek = null;
}

export async function generateDek(): Promise<CryptoKey> {
  return requireSubtle().generateKey({ name: ALGO, length: KEY_LENGTH }, true, [
    "encrypt",
    "decrypt",
  ]);
}

export async function exportDekRaw(key: CryptoKey): Promise<string> {
  const raw = await requireSubtle().exportKey("raw", key);
  return bytesToBase64(raw);
}

export async function importDekRaw(b64: string): Promise<CryptoKey> {
  const raw = base64ToBytes(b64);
  // Copy into a fresh ArrayBuffer — some runtimes reject SharedArrayBuffer views.
  const copy = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
  return requireSubtle().importKey("raw", copy, { name: ALGO, length: KEY_LENGTH }, true, [
    "encrypt",
    "decrypt",
  ]);
}

export async function encryptJson(key: CryptoKey, value: unknown): Promise<EncryptedEnvelope> {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const plaintext = new TextEncoder().encode(JSON.stringify(value));
  const ct = await requireSubtle().encrypt({ name: ALGO, iv }, key, plaintext);
  return { v: 1, iv: bytesToBase64(iv), ct: bytesToBase64(ct) };
}

export async function decryptJson<T>(key: CryptoKey, envelope: EncryptedEnvelope): Promise<T> {
  if (envelope.v !== 1 || typeof envelope.iv !== "string" || typeof envelope.ct !== "string") {
    throw new Error("offline vault: unrecognized ciphertext envelope");
  }
  const iv = base64ToBytes(envelope.iv);
  const ct = base64ToBytes(envelope.ct);
  const ivCopy = iv.buffer.slice(iv.byteOffset, iv.byteOffset + iv.byteLength);
  const ctCopy = ct.buffer.slice(ct.byteOffset, ct.byteOffset + ct.byteLength);
  try {
    const plain = await requireSubtle().decrypt(
      { name: ALGO, iv: new Uint8Array(ivCopy) },
      key,
      new Uint8Array(ctCopy),
    );
    return JSON.parse(new TextDecoder().decode(plain)) as T;
  } catch (err) {
    throw new Error(
      `offline vault: decrypt failed (tampered or wrong key): ${
        err instanceof Error ? err.message : String(err)
      }`,
      { cause: err },
    );
  }
}

export function isEncryptedEnvelope(value: unknown): value is EncryptedEnvelope {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return v.v === 1 && typeof v.iv === "string" && typeof v.ct === "string";
}

/**
 * Install a DEK into the in-memory cache. Called by offlineDb after loading
 * or creating the persisted key material.
 */
export function cacheDek(key: CryptoKey): void {
  cachedDek = key;
}

export function getCachedDek(): CryptoKey | null {
  return cachedDek;
}

export function clearCachedDek(): void {
  cachedDek = null;
}
