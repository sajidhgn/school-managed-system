import { useSyncExternalStore } from "react";

import type { AttendanceStatus } from "@/lib/api/types";

import { idbGet, idbSet } from "./idb";

/**
 * Registers taken while offline, kept on this device until they reach the server.
 *
 * =============================================================================
 * ONLY WHAT THE TEACHER CHANGED IS KEPT
 * =============================================================================
 *   `changes` holds the students the teacher tapped, not the whole register. The
 *   backend's mark endpoint is partial for the same reason: if the register was
 *   already half-marked online before the connection dropped, replaying a full
 *   all-present copy would quietly undo those absences. Sending only the taps
 *   cannot overwrite anything the teacher did not touch.
 *
 * One entry per section per date (whole-day registers, period 0 — what the board
 * opens). Saving again for the same section merges into it.
 *
 * Scoped to one user on one campus: an org-level principal who switches campus does
 * not see, or send, the other campus's queue under the wrong school.
 */

export interface OfflineRegister {
  /** `${sectionId}:${date}` */
  id: string;
  sectionId: string;
  /** "Grade 5 · A", for the sync panel. */
  sectionLabel: string;
  /** `YYYY-MM-DD`, the register's own date — not the day it is synced. */
  date: string;
  /** Student id → status, for the students the teacher changed. */
  changes: Record<string, AttendanceStatus>;
  /** Submit the register after applying the changes. */
  submit: boolean;
  /** `failed` stops retrying until the teacher retries or discards it. */
  state: "pending" | "failed";
  /** Why it failed, or a note on a pending one (e.g. "sign in again"). */
  error: string | null;
  updatedAt: number;
}

type Listener = () => void;

const EMPTY: OfflineRegister[] = [];
let scope: string | null = null;
let items: OfflineRegister[] = EMPTY;
const listeners = new Set<Listener>();

const storageKey = (forScope: string) => `outbox:${forScope}`;

function emit() {
  for (const listener of listeners) listener();
}

async function persist() {
  if (scope) await idbSet(storageKey(scope), items);
}

/** Switch to a user's campus queue, loading it from the device. */
export async function loadOutbox(nextScope: string): Promise<void> {
  scope = nextScope;
  const saved = await idbGet<OfflineRegister[]>(storageKey(nextScope));
  // The scope may have changed again while reading.
  if (scope !== nextScope) return;
  items = Array.isArray(saved) ? saved : EMPTY;
  emit();
}

export function getOutbox(): OfflineRegister[] {
  return items;
}

export function subscribeOutbox(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The queue, re-rendering when it changes. */
export function useOutbox(): OfflineRegister[] {
  return useSyncExternalStore(subscribeOutbox, getOutbox, () => EMPTY);
}

export function registerId(sectionId: string, date: string): string {
  return `${sectionId}:${date}`;
}

/**
 * Keep a register on the device.
 *
 * `merge` (a save that fell back to the device mid-way) adds to an earlier save for
 * the same section and date: later taps win, and "submit" sticks once asked for.
 * `replace` (the offline register, which started from the queued copy and shows the
 * whole picture) overwrites it, so a tap undone there is undone in the queue too.
 */
export async function saveOfflineRegister(
  input: {
    sectionId: string;
    sectionLabel: string;
    date: string;
    changes: Record<string, AttendanceStatus>;
    submit: boolean;
  },
  mode: "merge" | "replace" = "merge",
): Promise<void> {
  const id = registerId(input.sectionId, input.date);
  const existing = mode === "merge" ? items.find((item) => item.id === id) : undefined;
  const next: OfflineRegister = {
    id,
    sectionId: input.sectionId,
    sectionLabel: input.sectionLabel,
    date: input.date,
    changes: { ...(existing?.changes ?? {}), ...input.changes },
    submit: input.submit || (existing?.submit ?? false),
    state: "pending",
    error: null,
    updatedAt: Date.now(),
  };
  items = [...items.filter((item) => item.id !== id), next];
  emit();
  await persist();
}

export async function updateOfflineRegister(
  id: string,
  patch: Partial<Pick<OfflineRegister, "state" | "error">>,
): Promise<void> {
  items = items.map((item) => (item.id === id ? { ...item, ...patch } : item));
  emit();
  await persist();
}

export async function removeOfflineRegister(id: string): Promise<void> {
  items = items.filter((item) => item.id !== id);
  emit();
  await persist();
}
