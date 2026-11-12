import { ApiError, isOfflineError } from "@/lib/api/errors";
import { attendanceApi } from "@/lib/api/resources/attendance";

import {
  getOutbox,
  removeOfflineRegister,
  updateOfflineRegister,
  type OfflineRegister,
} from "./attendance-outbox";

/**
 * Send registers taken offline to the server.
 *
 * =============================================================================
 * EVERY STEP IS SAFE TO REPEAT
 * =============================================================================
 *   A sync can be cut off anywhere — the connection drops again, the tab closes —
 *   and the item stays queued until all of it has succeeded. So each step must be
 *   harmless the second time:
 *
 *     1. OPEN the register for the section and date. The backend's open is
 *        idempotent: it returns the existing register (draft or submitted).
 *     2. MARK only the students whose server status differs from the teacher's.
 *        Re-sending a status the server already has is skipped, not rewritten.
 *     3. SUBMIT, if asked.
 *
 *   If step 3 succeeded but the queue entry survived, the next pass opens a
 *   SUBMITTED register whose statuses already match: that is recognised as done.
 *   A submitted register that does NOT match was submitted by someone else first.
 *   Overwriting it would be an amendment nobody approved, so the item is set aside
 *   for the teacher to compare and discard.
 *
 * Errors split three ways: no connection or a server fault stops the run and keeps
 * everything queued; an ended session stops it with a note; a refusal (locked
 * register, removed section) fails just that item with the server's reason.
 */

export interface SyncResult {
  synced: number;
  failed: number;
  /** The run stopped early (offline again, server fault, session ended). */
  stopped: boolean;
}

export interface SyncMessages {
  alreadySubmitted: string;
  signInAgain: string;
}

const LOCK_NAME = "schoolyar-attendance-sync";

/** Run one pass over the queue. Concurrent calls (two tabs, two triggers) skip. */
export async function syncAttendanceOutbox(messages: SyncMessages): Promise<SyncResult | null> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks) {
    return locks.request(LOCK_NAME, { ifAvailable: true }, async (lock) =>
      lock ? runPass(messages) : null,
    );
  }
  return inProcess ? null : runPass(messages);
}

let inProcess = false;

async function runPass(messages: SyncMessages): Promise<SyncResult> {
  inProcess = true;
  const result: SyncResult = { synced: 0, failed: 0, stopped: false };
  try {
    for (const item of getOutbox().filter((entry) => entry.state === "pending")) {
      const outcome = await sendOne(item, messages);
      if (outcome === "synced") result.synced += 1;
      else if (outcome === "failed") result.failed += 1;
      else {
        result.stopped = true;
        break;
      }
    }
  } finally {
    inProcess = false;
  }
  return result;
}

async function sendOne(
  item: OfflineRegister,
  messages: SyncMessages,
): Promise<"synced" | "failed" | "stop"> {
  try {
    const session = await attendanceApi.open({
      section_id: item.sectionId,
      session_date: item.date,
      period: 0,
    });

    const current = new Map(session.entries.map((entry) => [entry.student_id, entry.status]));
    // A student who has left the section since is not on the register: skipped.
    const differing = Object.entries(item.changes).filter(
      ([studentId, status]) => current.has(studentId) && current.get(studentId) !== status,
    );

    if (session.status === "submitted") {
      if (differing.length === 0) {
        await removeOfflineRegister(item.id);
        return "synced";
      }
      await updateOfflineRegister(item.id, { state: "failed", error: messages.alreadySubmitted });
      return "failed";
    }

    if (differing.length > 0) {
      await attendanceApi.mark(
        session.id,
        differing.map(([student_id, status]) => ({
          student_id,
          status,
          minutes_late: null,
          remarks: null,
        })),
      );
    }
    if (item.submit) await attendanceApi.submit(session.id);

    await removeOfflineRegister(item.id);
    return "synced";
  } catch (error) {
    if (isOfflineError(error)) return "stop";
    if (error instanceof ApiError) {
      if (error.status === 401) {
        await updateOfflineRegister(item.id, { error: messages.signInAgain });
        return "stop";
      }
      if (error.status >= 500 || error.status === 429) return "stop";
      await updateOfflineRegister(item.id, { state: "failed", error: error.message });
      return "failed";
    }
    return "stop";
  }
}
