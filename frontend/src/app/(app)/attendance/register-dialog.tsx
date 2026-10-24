"use client";

import * as React from "react";
import { CircleCheck, Lock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import {
  useAttendanceSession,
  useMarkAttendance,
  useReopenRegister,
  useSubmitRegister,
} from "@/hooks/use-attendance";
import type { AttendanceEntryRead, AttendanceStatus } from "@/lib/api/types";

/**
 * The marking screen.
 *
 * =============================================================================
 * MARKING IS OPTIMISTIC-LOCAL AND SAVED IN ONE REQUEST
 * =============================================================================
 *   A teacher flips three or four absentees out of thirty, on a phone, on school
 *   wifi. Sending a request per tap would be thirty round-trips in the worst case
 *   and — worse — several of them can fail independently, leaving the register in
 *   a state neither the teacher nor the server can describe.
 *
 *   So taps mutate local state, and one PATCH carries the diff. That is also why
 *   the backend's mark endpoint is partial: the two halves were designed together.
 */

const STATUS_ORDER: AttendanceStatus[] = ["present", "absent", "late", "excused", "half_day"];

const STATUS_LABEL: Record<AttendanceStatus, string> = {
  present: "Present",
  absent: "Absent",
  late: "Late",
  excused: "Excused",
  half_day: "Half day",
};

/**
 * Colour carries meaning here, so it is paired with a label rather than used alone:
 * a register read by a colour-blind teacher must still be readable.
 *
 * The state tokens, matching `STATUS_META` (components/attendance/status.tsx), so a
 * status is the same colour in the register as on every analytics screen: green
 * in, amber partly in, red out, gray on leave. (This used to add a sky blue and a
 * violet of its own.)
 */
const STATUS_STYLE: Record<AttendanceStatus, string> = {
  present: "bg-success text-success-foreground border-success",
  absent: "bg-destructive text-destructive-foreground border-destructive",
  late: "bg-warning text-warning-foreground border-warning",
  excused: "bg-muted-foreground text-background border-muted-foreground",
  half_day: "bg-warning/20 text-foreground border-warning",
};

export function RegisterDialog({
  sessionId,
  onClose,
  canMark,
  canAmend,
}: {
  sessionId: string | null;
  onClose: () => void;
  canMark: boolean;
  canAmend: boolean;
}) {
  const query = useAttendanceSession(sessionId);
  const mark = useMarkAttendance();
  const submit = useSubmitRegister();
  const reopen = useReopenRegister();

  /** Local edits, keyed by student. Empty means "nothing changed yet". */
  const [pending, setPending] = React.useState<Record<string, AttendanceStatus>>({});
  const [reason, setReason] = React.useState("");

  const session = query.data;
  const isSubmitted = session?.status === "submitted";
  // Past the day after its date the register is locked, draft or not; the server
  // decides when, so the browser's clock cannot disagree with it.
  const isLocked = session?.locked ?? false;
  // A submitted or locked register is editable only by an amender. A submitted one
  // also needs a reason; a locked draft does not, since it was never asserted.
  const editable = isSubmitted || isLocked ? canAmend : canMark;

  React.useEffect(() => {
    // Discard local edits whenever the dialog switches registers, so yesterday's
    // half-finished taps cannot leak into today's section.
    setPending({});
    setReason("");
  }, [sessionId]);

  function statusOf(entry: AttendanceEntryRead): AttendanceStatus {
    return pending[entry.student_id] ?? entry.status;
  }

  const changed = React.useMemo(() => {
    if (!session) return [];
    return session.entries
      .filter((entry) => pending[entry.student_id] && pending[entry.student_id] !== entry.status)
      .map((entry) => ({
        student_id: entry.student_id,
        status: pending[entry.student_id],
        minutes_late: null,
        remarks: null,
      }));
  }, [session, pending]);

  async function handleSave() {
    if (!sessionId || changed.length === 0) return;
    await mark.mutateAsync({
      sessionId,
      entries: changed,
      // Only sent when amending. The backend requires it there and ignores it on a
      // draft, so passing it unconditionally would train users to type a reason for
      // an edit that needs none.
      reason: isSubmitted ? reason : undefined,
    });
    setPending({});
    setReason("");
  }

  async function handleSubmit() {
    if (!sessionId) return;
    if (changed.length > 0) await handleSave();
    await submit.mutateAsync(sessionId);
    onClose();
  }

  const counts = React.useMemo(() => {
    if (!session) return { present: 0, absent: 0 };
    let present = 0;
    let absent = 0;
    for (const entry of session.entries) {
      const status = statusOf(entry);
      if (status === "absent" || status === "excused") absent += 1;
      else present += 1;
    }
    return { present, absent };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, pending]);

  return (
    <Dialog open={sessionId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Register
            {isSubmitted && (
              <Badge variant="success">
                <CircleCheck className="mr-1 h-3 w-3" aria-hidden />
                Submitted
              </Badge>
            )}
            {isLocked && (
              <Badge variant="outline">
                <Lock className="mr-1 h-3 w-3" aria-hidden />
                Locked
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {session
              ? `${session.session_date} · ${counts.present} present, ${counts.absent} absent`
              : "Loading the roster…"}
          </DialogDescription>
        </DialogHeader>

        {query.isPending && (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        )}

        {session && (
          <div className="max-h-[50vh] space-y-1 overflow-y-auto pr-1">
            {session.entries.map((entry) => {
              const current = statusOf(entry);
              return (
                <div
                  key={entry.id}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {/* Roll number leads: a register is read against a printed
                          list in roll order, not searched by name. */}
                      {entry.roll_number ? `${entry.roll_number}. ` : ""}
                      {entry.full_name}
                    </p>
                    <p className="text-xs text-muted-foreground">{entry.admission_number}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {STATUS_ORDER.map((status) => (
                      <button
                        key={status}
                        type="button"
                        disabled={!editable}
                        aria-pressed={current === status}
                        aria-label={`${STATUS_LABEL[status]} — ${entry.full_name}`}
                        onClick={() =>
                          setPending((prev) => ({ ...prev, [entry.student_id]: status }))
                        }
                        className={[
                          "rounded border px-2 py-1 text-xs transition disabled:opacity-50",
                          current === status
                            ? STATUS_STYLE[status]
                            : "bg-background text-muted-foreground hover:bg-muted",
                        ].join(" ")}
                      >
                        {STATUS_LABEL[status]}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {isSubmitted && canAmend && changed.length > 0 && (
          <div className="space-y-1">
            <Label htmlFor="amend-reason">Reason for the correction</Label>
            <Input
              id="amend-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Note from mother received after submission"
            />
            <p className="text-xs text-muted-foreground">
              Required. Recorded in the audit log alongside what changed.
            </p>
          </div>
        )}

        {isLocked && !canAmend ? (
          <p className="text-xs text-muted-foreground">
            Attendance for this date is locked. Registers can be changed until the end
            of the following day; correcting it now needs the &ldquo;amend
            attendance&rdquo; permission.
          </p>
        ) : (
          isSubmitted &&
          !canAmend && (
            <p className="text-xs text-muted-foreground">
              This register has been submitted. Correcting it needs the
              &ldquo;amend attendance&rdquo; permission.
            </p>
          )
        )}

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>

          {isSubmitted && canAmend && (
            <Button
              variant="outline"
              disabled={reopen.isPending || reason.trim().length < 3}
              onClick={() =>
                sessionId && void reopen.mutateAsync({ sessionId, reason: reason.trim() })
              }
            >
              Reopen
            </Button>
          )}

          {editable && (
            <Button
              disabled={
                changed.length === 0 ||
                mark.isPending ||
                (isSubmitted && reason.trim().length < 3)
              }
              onClick={() => void handleSave()}
            >
              Save {changed.length > 0 ? `(${changed.length})` : ""}
            </Button>
          )}

          {!isSubmitted && canMark && (!isLocked || canAmend) && (
            <Button disabled={submit.isPending} onClick={() => void handleSubmit()}>
              Submit register
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
