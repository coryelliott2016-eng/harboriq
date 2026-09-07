import { fieldApi } from "./services";
import type { PendingAction } from "./offlineQueue";

/**
 * Translates one queued field action into the real HTTP call, per `kind`.
 * This is the `ActionSender` passed to `replayQueue` (see offlineQueue.ts).
 * Every branch forwards the action's own `idempotencyKey`, so a retried
 * send after a dropped response is a safe no-op server-side.
 *
 * Also forwards `client_queued_at` (the original enqueue timestamp) so the
 * server can audit offline-replay age (marine threat model Scenario 3).
 */
export async function sendFieldAction(action: PendingAction): Promise<void> {
  const client_queued_at = action.createdAt;
  switch (action.kind) {
    case "clock_in":
      await fieldApi.clockIn(action.jobId, {
        idempotency_key: action.idempotencyKey,
        client_queued_at,
      });
      return;
    case "clock_out":
      await fieldApi.clockOut(action.jobId, {
        idempotency_key: action.idempotencyKey,
        client_queued_at,
      });
      return;
    case "attachment": {
      const payload = action.payload as {
        kind: "photo" | "signature" | "other";
        data: string;
        content_type?: string;
      };
      await fieldApi.addAttachment(action.jobId, {
        kind: payload.kind,
        data: payload.data,
        content_type: payload.content_type,
        idempotency_key: action.idempotencyKey,
        client_queued_at,
      });
      return;
    }
    default: {
      const _exhaustive: never = action.kind;
      throw new Error(`Unknown queued action kind: ${String(_exhaustive)}`);
    }
  }
}
