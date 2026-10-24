import type { CSSProperties } from "react";
import { BatteryFull, Camera, CheckCheck, ChevronLeft, Mic, Signal, Wifi } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The WhatsApp attendance conversation, as a still phone: a teacher sends roll
 * numbers, corrects one, replies OK. The messages come in one after another once,
 * on the diary demo's phone and bubble styles; reduced motion shows them at once.
 *
 * Like the other demos it is an English illustration (lang="en", aria-hidden),
 * described for screen readers in the visitor's language by `description`.
 */

type Message = { from: "teacher" | "agent"; body: string; time: string };

const MESSAGES: Message[] = [
  { from: "teacher", body: "Nursery-A absent 12, 13, 15", time: "8:05" },
  {
    from: "agent",
    body: "📋 Attendance · Nursery-A\n❌ Absent (3)\n12 · Ali Khan\n13 · Sara Ahmed\n15 · Bilal Raza\n✅ 27 of 30 present\nReply OK to submit.",
    time: "8:05",
  },
  { from: "teacher", body: "13 was present", time: "8:06" },
  {
    from: "agent",
    body: "❌ Absent (2)\n12 · Ali Khan\n15 · Bilal Raza\n✅ 28 of 30 present\nReply OK to submit.",
    time: "8:06",
  },
  { from: "teacher", body: "ok", time: "8:06" },
  { from: "agent", body: "✅ Submitted for Nursery-A: 28 present, 2 absent.", time: "8:06" },
];

export function AttendanceChatDemo({ description }: { description: string }) {
  return (
    <>
      <p className="sr-only">{description}</p>
      <div className="mk-stage mk-stage--phone" dir="ltr" lang="en" aria-hidden>
        <div className="mk-phone">
          <div className="mk-phone__frame">
            <div className="mk-phone__screen">
              <div className="mk-phone__status">
                <span>8:06</span>
                <span className="flex items-center gap-1">
                  <Signal className="size-3" />
                  <Wifi className="size-3" />
                  <BatteryFull className="size-3.5" />
                </span>
              </div>
              <div className="mk-phone__head">
                <ChevronLeft className="size-4 opacity-70" />
                <span className="mk-phone__avatar">S</span>
                <span className="min-w-0 leading-tight">
                  <b className="block truncate text-[13px]">Sunrise School</b>
                  <span className="block truncate text-[10.5px] text-[var(--mk-chat-meta)]">SchoolYar assistant</span>
                </span>
              </div>

              <div className="mk-phone__chat">
                <span className="mk-day">Today</span>
                {MESSAGES.map((message, i) => (
                  <div
                    key={i}
                    className="mk-msg"
                    style={{ animationDelay: `${0.4 + i * 0.7}s` } as CSSProperties}
                  >
                    <div>
                      <div
                        className={cn(
                          "mk-bubble whitespace-pre-line",
                          message.from === "teacher" && "mk-bubble--out",
                        )}
                      >
                        {message.body}
                        <span className="mk-bubble__meta">
                          {message.time}
                          {message.from === "teacher" ? <CheckCheck className="mk-bubble__ticks size-3.5" /> : null}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mk-phone__input">
                <span className="mk-phone__field">
                  <span className="flex-1">Message</span>
                  <Camera className="size-4" />
                </span>
                <span className="mk-phone__mic">
                  <Mic className="size-4" />
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
