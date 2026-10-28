"use client";

import {
  BatteryFull,
  Camera,
  CheckCheck,
  ChevronLeft,
  MessageCircle,
  Mic,
  Pause,
  Play,
  Signal,
  Wifi,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The landing page's hero: the diary agent's real flow (docs/modules/diary-agent.md),
 * played on a loop. A teacher photographs the paper diary, SchoolYar reads it and
 * replies with the formatted diary, the teacher adds a line and says OK, and it is
 * posted to the class's parents' group.
 *
 * Plays only while on screen and the tab is visible, has a pause button (WCAG
 * 2.2.2), and shows the finished conversation, still, to anyone who prefers
 * reduced motion.
 */

type Message = { from: "teacher" | "school"; photo?: boolean; body?: ReactNode; time: string };

const MESSAGES: Message[] = [
  { from: "teacher", photo: true, time: "2:41 pm" },
  { from: "school", body: "Got it - reading the diary page… 📖", time: "2:41 pm" },
  {
    from: "school",
    body: (
      <>
        Here is the diary for <b>Grade 9-A</b>, ready for “9-A Parents”:{"\n\n"}📚{" "}
        <b>Diary · Thursday 15 Oct</b>
        {"\n"}Maths: Exercise 4.3, Q1–6{"\n"}English: Learn the poem “Daffodils”{"\n"}Urdu: Lesson 5
        exercise{"\n"}Science: Bring the lab notebook{"\n\n"}Reply OK to post it. To change
        something, just tell me.
      </>
    ),
    time: "2:42 pm",
  },
  { from: "teacher", body: "add computer test on monday", time: "2:42 pm" },
  {
    from: "school",
    body: (
      <>
        Updated. Added <b>Computer: Test on Monday</b>. Reply OK to post it.
      </>
    ),
    time: "2:42 pm",
  },
  { from: "teacher", body: "ok 👍", time: "2:43 pm" },
  { from: "school", body: "✅ Posted to “9-A Parents”.", time: "2:43 pm" },
];

const DIARY_LINES = [
  "Maths: Ex 4.3, Q1-6",
  "English: poem Daffodils",
  "Urdu: lesson 5 exercise",
  "Science: lab notebook",
];

type Frame = {
  step: number;
  /** How many of MESSAGES are on screen. */
  shown: number;
  ms: number;
  typing?: boolean;
  diary?: "snap" | "reading" | "read";
  notify?: boolean;
};

const FRAMES: Frame[] = [
  { step: 0, shown: 0, ms: 1200, diary: "snap" },
  { step: 0, shown: 1, ms: 800 },
  { step: 1, shown: 1, ms: 700, typing: true },
  { step: 1, shown: 2, ms: 1900, diary: "reading" },
  { step: 1, shown: 2, ms: 900, typing: true, diary: "read" },
  { step: 2, shown: 3, ms: 3000, diary: "read" },
  { step: 2, shown: 4, ms: 900, diary: "read" },
  { step: 2, shown: 4, ms: 900, typing: true, diary: "read" },
  { step: 2, shown: 5, ms: 2100, diary: "read" },
  { step: 3, shown: 6, ms: 700, diary: "read" },
  { step: 3, shown: 6, ms: 700, typing: true, diary: "read" },
  { step: 3, shown: 7, ms: 4800, diary: "read", notify: true },
];

const LAST = FRAMES.length - 1;

const STEP_MS = [0, 1, 2, 3].map((step) =>
  FRAMES.filter((f) => f.step === step).reduce((sum, f) => sum + f.ms, 0),
);

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia(REDUCED_MOTION);
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

/**
 * The words around the demo come from the page's language; the conversation
 * itself stays in English, as teachers here mostly type it.
 */
export function DiaryDemo({
  steps,
  pauseLabel,
  playLabel,
  description,
}: {
  steps: readonly string[];
  pauseLabel: string;
  playLabel: string;
  description: string;
}) {
  const reduced = usePrefersReducedMotion();
  const stageRef = useRef<HTMLDivElement>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [cycle, setCycle] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [onScreen, setOnScreen] = useState(false);
  const [tabVisible, setTabVisible] = useState(true);
  const remaining = useRef(FRAMES[0]!.ms);

  useEffect(() => {
    const node = stageRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(Boolean(entry?.isIntersecting)), {
      threshold: 0.2,
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onVisibility = () => setTabVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const running = playing && onScreen && tabVisible && !reduced;

  // A new frame gets its full duration. Declared before the timer so it runs first.
  useEffect(() => {
    remaining.current = FRAMES[frameIndex]!.ms;
  }, [frameIndex]);

  // Pausing keeps what is left of the current frame, so the progress bar (which
  // pauses with it in CSS) and the conversation stay in step.
  useEffect(() => {
    if (!running) return;
    const started = performance.now();
    const timer = window.setTimeout(() => {
      const next = (frameIndex + 1) % FRAMES.length;
      if (next === 0) setCycle((c) => c + 1);
      setFrameIndex(next);
    }, remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(0, remaining.current - (performance.now() - started));
    };
  }, [running, frameIndex]);

  const frame = FRAMES[reduced ? LAST : frameIndex]!;

  return (
    <div className="mk-rise" style={{ "--i": 2 } as CSSProperties}>
      <p className="sr-only">{description}</p>

      <div ref={stageRef} className="mk-stage" dir="ltr" lang="en" aria-hidden>
        <DiaryPage state={frame.diary} />
        <Phone frame={frame} cycle={cycle} />
        <div className={cn("mk-notify", frame.notify && "is-on")}>
          <div className="mk-notify__card">
            <span className="grid size-9 shrink-0 place-items-center rounded-[0.6rem] bg-[#2447f5] text-white">
              <MessageCircle className="size-5" />
            </span>
            <div className="min-w-0 text-[12.5px] leading-snug">
              <div className="flex items-baseline justify-between gap-2">
                <b>9-A Parents</b>
                <span className="text-[11px] text-mk-muted">now</span>
              </div>
              <p className="truncate">Sunrise School: 📚 Diary · Thursday 15 Oct</p>
              <p className="truncate text-mk-muted">Maths: Exercise 4.3, Q1–6 · English: Learn the…</p>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto mt-6 flex max-w-[34rem] items-start gap-3">
        <ol className={cn("mk-steps grid flex-1 grid-cols-4 gap-2.5", !running && "is-paused")}>
          {steps.map((label, i) => {
            const done = i < frame.step || (reduced && i === frame.step);
            const active = !reduced && i === frame.step;
            return (
              <li
                key={label}
                className={cn("mk-steps__item", done && "is-done", active && "is-active")}
                aria-current={active ? "step" : undefined}
              >
                <div className="mk-steps__bar">
                  <span key={active ? `${cycle}-${i}` : i} style={{ "--dur": `${STEP_MS[i]}ms` } as CSSProperties} />
                </div>
                <p
                  className={cn(
                    "mt-2 text-[0.78rem] leading-snug transition-colors sm:text-[0.82rem]",
                    active || done ? "text-mk-text" : "text-mk-muted",
                  )}
                >
                  <span className="font-mk-mono text-mk-ink">{i + 1}</span> {label}
                </p>
              </li>
            );
          })}
        </ol>
        {reduced ? null : (
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            aria-label={playing ? pauseLabel : playLabel}
            className="grid size-8 shrink-0 place-items-center rounded-control border border-mk-line bg-mk-card text-mk-muted transition-colors hover:border-mk-ink hover:text-mk-ink"
          >
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          </button>
        )}
      </div>
    </div>
  );
}

function DiaryPage({ state }: { state: Frame["diary"] }) {
  return (
    <div
      className={cn(
        "mk-diary",
        state === "snap" && "is-snap",
        state === "reading" && "is-reading",
        state === "read" && "is-read",
      )}
    >
      <div className="mk-diary__page">
        {/* Kept to the left: the phone covers the right side of the page. */}
        <div className="mk-diary__head">
          <span>
            Class 9-A
            <br />
            Thursday 15-10-26
          </span>
        </div>
        <div className="mk-diary__lines">
          {DIARY_LINES.map((line, i) => (
            <span key={line} className="mk-diary__line" style={{ "--i": i } as CSSProperties}>
              {line}
            </span>
          ))}
        </div>
        <p className="mk-diary__sign">Ms. Hina</p>
        <div className="mk-diary__scan" />
        <div className="mk-diary__flash" />
      </div>
      <div className="mk-diary__finder">
        <span />
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

function Phone({ frame, cycle }: { frame: Frame; cycle: number }) {
  return (
    <div className="mk-phone">
      <div className="mk-phone__frame">
        <div className="mk-phone__screen">
          <div className="mk-phone__status">
            <span>2:43</span>
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

          <div key={cycle} className="mk-phone__chat">
            <span className="mk-day">Today</span>
            {MESSAGES.slice(0, frame.shown).map((message, i) => (
              <div key={i} className="mk-msg">
                <div>
                  <Bubble message={message} />
                </div>
              </div>
            ))}
            {frame.typing ? (
              <div className="mk-msg">
                <div>
                  <div className="mk-bubble mk-typing">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </div>
            ) : null}
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
  );
}

function Bubble({ message }: { message: Message }) {
  const out = message.from === "teacher";
  return (
    <div className={cn("mk-bubble", out && "mk-bubble--out")}>
      {message.photo ? (
        <div className="mk-thumb">
          {[16, 28, 40, 52, 64, 76].map((top, i) => (
            <i key={top} style={{ top, width: `${[58, 44, 62, 50, 38, 20][i]}%` }} />
          ))}
        </div>
      ) : (
        message.body
      )}
      <span className="mk-bubble__meta">
        {message.time}
        {out ? <CheckCheck className="mk-bubble__ticks size-3.5" /> : null}
      </span>
    </div>
  );
}
