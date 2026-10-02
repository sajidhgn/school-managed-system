/**
 * Draws a section's diary page as a PNG -- the sheet schools forward to parents.
 *
 * WHY A CANVAS AND NOT A SCREENSHOT OF THE DOM
 *   The sheet goes out on WhatsApp, so it has to be an IMAGE, sized for a phone
 *   screen, identical on every device. Rasterising the DOM needs a library and
 *   inherits whatever the browser's layout and fonts did that day; drawing it
 *   directly is ~200 lines, needs nothing, and wraps Urdu and English text the
 *   same way every time.
 *
 * Layout follows the paper diary schools already send: crest on both sides of the
 * school name, a Date / Day line, then Subject | Assignments rows with the subject
 * in a filled cell and the homework on ruled lines beside it.
 */

import type { DiaryPage } from "@/lib/api/types";

export type DiaryBranding = {
  schoolName: string;
  /** Second header line -- the campus town, as on most printed diaries. */
  subtitle: string | null;
  logoUrl: string | null;
  /** Fill for the subject cells and header; defaults to diary navy. */
  primaryColor: string | null;
};

const WIDTH = 1600;
const PAD = 40;
const NAVY = "#1d3f8f";
const INK = "#111827";
const RULE = "#c7d2e3";
// Latin faces FIRST: the browser falls through per glyph, so Urdu letters still
// reach the Nastaliq faces, while digits and brackets stay in the Latin face. Urdu
// first draws "Pg 85" with Nastaliq numerals in the middle of an English line.
const FONT_STACK =
  '"Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "Noto Naskh Arabic", sans-serif';

const RTL_CHAR = /[֐-ࣿיִ-﷿ﹰ-﻿]/;

/** Direction of the first strong character -- what `dir="auto"` does in HTML. */
function isRtl(text: string): boolean {
  for (const ch of text) {
    if (RTL_CHAR.test(ch)) return true;
    if (/[A-Za-z]/.test(ch)) return false;
  }
  return false;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split(/\r?\n/)) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      lines.push("");
      continue;
    }
    let line = "";
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word;
      if (ctx.measureText(candidate).width <= maxWidth || !line) {
        line = candidate;
      } else {
        lines.push(line);
        line = word;
      }
    }
    lines.push(line);
  }
  return lines;
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    // Without this a cross-origin logo taints the canvas and `toBlob` throws.
    if (!src.startsWith("data:")) img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

function shade(hex: string, amount: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const channel = (shift: number) =>
    Math.max(0, Math.min(255, ((n >> shift) & 0xff) + Math.round(255 * amount)));
  return `rgb(${channel(16)}, ${channel(8)}, ${channel(0)})`;
}

function filledCell(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  color: string,
) {
  const gradient = ctx.createLinearGradient(x, y, x, y + h);
  gradient.addColorStop(0, shade(color, 0.08));
  gradient.addColorStop(1, shade(color, -0.08));
  ctx.fillStyle = gradient;
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = shade(color, -0.2);
  ctx.lineWidth = 3;
  ctx.strokeRect(x, y, w, h);
}

/** Long day name and a compact date, e.g. ["Monday", "28 Sep 2026"]. */
export function diaryDayLabels(isoDate: string): { day: string; date: string } {
  // Noon UTC, so no timezone can move an ISO date onto the neighbouring day.
  const d = new Date(`${isoDate}T12:00:00Z`);
  return {
    day: new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" }).format(d),
    date: new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(d),
  };
}

export async function renderDiaryImage(
  page: DiaryPage,
  branding: DiaryBranding,
  { includeEmpty = false }: { includeEmpty?: boolean } = {},
): Promise<Blob> {
  const color = branding.primaryColor || NAVY;
  const rows = page.rows.filter((row) => includeEmpty || (row.content ?? "").trim());
  const logo = branding.logoUrl ? await loadImage(branding.logoUrl) : null;

  // Fonts the sheet uses must be ready before measuring, or the first render
  // wraps with fallback metrics and the second does not.
  if (typeof document !== "undefined" && "fonts" in document) {
    await document.fonts.ready;
  }

  const canvas = document.createElement("canvas");
  const measure = canvas.getContext("2d");
  if (!measure) throw new Error("Canvas is not available in this browser.");

  const tableX = PAD + 20;
  const tableW = WIDTH - 2 * tableX;
  const subjectW = Math.round(tableW * 0.28);
  const gap = 22;
  const textX = tableX + subjectW + gap;
  const textW = tableW - subjectW - gap;
  const lineH = 64;
  const bodyFont = `500 40px ${FONT_STACK}`;

  // Pass 1: measure every row so the canvas can be sized before anything is drawn.
  measure.font = bodyFont;
  const measured = rows.map((row) => {
    const text = (row.content ?? "").trim() || "—";
    const lines = wrap(measure, text, textW - 60);
    return { row, text, lines, height: Math.max(2, lines.length + 1) * lineH };
  });

  const headerH = 230;
  const metaH = 110;
  const tableHeadH = 96;
  const rowGap = 26;
  const footerH = page.class_teacher_name ? 90 : 40;
  const bodyH = measured.reduce((sum, m) => sum + m.height + rowGap, 0);
  const emptyH = measured.length === 0 ? 160 : 0;
  const height =
    headerH + metaH + tableHeadH + rowGap + bodyH + emptyH + footerH + PAD * 2;

  canvas.width = WIDTH;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not available in this browser.");

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, WIDTH, height);
  ctx.textBaseline = "middle";

  // --- Header: crest | school name | crest ---------------------------------
  const logoSize = 170;
  if (logo) {
    const fit = (img: HTMLImageElement, x: number) => {
      const scale = Math.min(logoSize / img.width, logoSize / img.height);
      const w = img.width * scale;
      const h = img.height * scale;
      ctx.drawImage(img, x + (logoSize - w) / 2, PAD + (logoSize - h) / 2, w, h);
    };
    fit(logo, PAD);
    fit(logo, WIDTH - PAD - logoSize);
  }

  const nameMaxW = WIDTH - 2 * (PAD + logoSize + 30);
  ctx.textAlign = "center";
  ctx.fillStyle = color;
  let nameSize = 76;
  ctx.font = `800 ${nameSize}px ${FONT_STACK}`;
  while (ctx.measureText(branding.schoolName.toUpperCase()).width > nameMaxW && nameSize > 40) {
    nameSize -= 2;
    ctx.font = `800 ${nameSize}px ${FONT_STACK}`;
  }
  const nameY = branding.subtitle ? PAD + 62 : PAD + 95;
  const schoolName = branding.schoolName.toUpperCase();
  ctx.fillText(schoolName, WIDTH / 2, nameY);
  const underline = (text: string, y: number, size: number) => {
    const w = Math.min(ctx.measureText(text).width, nameMaxW);
    ctx.fillRect(WIDTH / 2 - w / 2, y + size * 0.55, w, 5);
  };
  underline(schoolName, nameY, nameSize);
  if (branding.subtitle) {
    const sub = branding.subtitle.toUpperCase();
    ctx.font = `800 64px ${FONT_STACK}`;
    ctx.fillText(sub, WIDTH / 2, nameY + 100);
    underline(sub, nameY + 100, 64);
  }

  // --- Frame ---------------------------------------------------------------
  const frameY = PAD + headerH - 20;
  ctx.strokeStyle = color;
  ctx.lineWidth = 4;
  ctx.strokeRect(PAD, frameY, WIDTH - 2 * PAD, height - frameY - PAD);

  // --- Date / class / day ---------------------------------------------------
  const { day, date } = diaryDayLabels(page.entry_date);
  const metaY = frameY + metaH / 2 + 8;
  ctx.font = `600 46px ${FONT_STACK}`;
  ctx.fillStyle = color;
  ctx.textAlign = "left";
  ctx.fillText(`Date: ${date}`, tableX, metaY);
  ctx.textAlign = "right";
  ctx.fillText(`Day: ${day}`, WIDTH - tableX, metaY);
  ctx.textAlign = "center";
  ctx.fillStyle = INK;
  ctx.font = `700 46px ${FONT_STACK}`;
  ctx.fillText(`${page.class_name} – ${page.section_name}`, WIDTH / 2, metaY);

  // --- Column heads -------------------------------------------------------
  let y = frameY + metaH;
  filledCell(ctx, tableX, y, subjectW, tableHeadH, color);
  filledCell(ctx, textX, y, textW, tableHeadH, color);
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 50px ${FONT_STACK}`;
  ctx.fillText("Subject", tableX + subjectW / 2, y + tableHeadH / 2);
  ctx.fillText("Assignments", textX + textW / 2, y + tableHeadH / 2);
  y += tableHeadH + rowGap;

  // --- Rows ---------------------------------------------------------------
  for (const { row, lines, height: rowH } of measured) {
    filledCell(ctx, tableX, y, subjectW, rowH, color);
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.direction = isRtl(row.subject_name) ? "rtl" : "ltr";
    let subjectSize = 54;
    ctx.font = `700 ${subjectSize}px ${FONT_STACK}`;
    const subjectLines = () => wrap(ctx, row.subject_name, subjectW - 30);
    let sLines = subjectLines();
    while (sLines.length * subjectSize * 1.15 > rowH - 20 && subjectSize > 30) {
      subjectSize -= 4;
      ctx.font = `700 ${subjectSize}px ${FONT_STACK}`;
      sLines = subjectLines();
    }
    const sTop = y + rowH / 2 - ((sLines.length - 1) * subjectSize * 1.15) / 2;
    sLines.forEach((line, i) =>
      ctx.fillText(line, tableX + subjectW / 2, sTop + i * subjectSize * 1.15),
    );

    // The assignment box, ruled like an exercise book.
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(textX, y, textW, rowH);
    // Rules UNDER each line of text, as in an exercise book; extended through the
    // spare space so a short entry still sits on a ruled box.
    const top = y + rowH / 2 - ((lines.length - 1) * lineH) / 2;
    ctx.strokeStyle = RULE;
    ctx.lineWidth = 2;
    for (let ry = top + lineH * 0.5; ry < y + rowH - 4; ry += lineH) {
      ctx.beginPath();
      ctx.moveTo(textX, ry);
      ctx.lineTo(textX + textW, ry);
      ctx.stroke();
    }
    for (let ry = top - lineH * 0.5; ry > y + 4; ry -= lineH) {
      ctx.beginPath();
      ctx.moveTo(textX, ry);
      ctx.lineTo(textX + textW, ry);
      ctx.stroke();
    }
    ctx.strokeStyle = shade(color, -0.2);
    ctx.lineWidth = 3;
    ctx.strokeRect(textX, y, textW, rowH);

    ctx.fillStyle = INK;
    ctx.font = bodyFont;
    lines.forEach((line, i) => {
      ctx.direction = isRtl(line) ? "rtl" : "ltr";
      ctx.fillText(line, textX + textW / 2, top + i * lineH);
    });
    ctx.direction = "ltr";
    y += rowH + rowGap;
  }

  if (measured.length === 0) {
    ctx.fillStyle = "#6b7280";
    ctx.font = `500 44px ${FONT_STACK}`;
    ctx.fillText("No homework today.", WIDTH / 2, y + 60);
    y += emptyH;
  }

  if (page.class_teacher_name) {
    ctx.textAlign = "right";
    ctx.fillStyle = "#4b5563";
    ctx.font = `500 38px ${FONT_STACK}`;
    ctx.fillText(`Class teacher: ${page.class_teacher_name}`, WIDTH - tableX, y + 30);
  }

  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Could not create the image."))),
      "image/png",
    ),
  );
}
