"use client";

import * as React from "react";
import { Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * A logo can be an uploaded image or a pasted link — the same two shapes the
 * API accepts (`LOGO_URL_PATTERN` in the tenancy schemas): `https?://…` or
 * `data:image/…`.
 *
 * WHY THE UPLOAD BECOMES A DATA URI RATHER THAN A FILE ON A SERVER
 *   There is no object store, and the browser is never told the FastAPI origin
 *   (everything rides the BFF proxy), so a served-file URL has nowhere to
 *   point. Instead the image is downscaled HERE, on a canvas, to a bounded
 *   data URI that travels through the ordinary JSON PATCH. That also means the
 *   proxy's text-only body handling is never asked to carry multipart.
 */

/** Longest edge after downscale. Logos render at ≤64px in the UI and small on
 * printed cards; 512 keeps them crisp on print without bloating responses. */
const MAX_EDGE = 512;

/** Refuse absurd source files before decoding: a 20 MB camera photo would
 * stall the tab just to be thrown away by the downscale. */
const MAX_FILE_BYTES = 8 * 1024 * 1024;

/** Mirror of the API's LogoUrl max_length; exceeding it would 422 on save. */
const MAX_DATA_URI_CHARS = 300_000;

/**
 * Downscale to a data URI. PNG first (logos want transparency); if the PNG
 * encodes too large — a photographic image, where PNG is the wrong codec —
 * fall back to JPEG on a white ground.
 */
async function fileToDataUri(file: File): Promise<string> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("The file could not be read as an image."));
      el.src = objectUrl;
    });

    const scale = Math.min(1, MAX_EDGE / Math.max(image.width, image.height, 1));
    const width = Math.max(1, Math.round(image.width * scale));
    const height = Math.max(1, Math.round(image.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("The image could not be processed.");
    context.drawImage(image, 0, 0, width, height);

    const png = canvas.toDataURL("image/png");
    if (png.length <= MAX_DATA_URI_CHARS) return png;

    // JPEG has no alpha channel; un-painted pixels would come out black.
    context.globalCompositeOperation = "destination-over";
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    const jpeg = canvas.toDataURL("image/jpeg", 0.85);
    if (jpeg.length <= MAX_DATA_URI_CHARS) return jpeg;
    throw new Error("The image is too complex to store — try a simpler or smaller logo.");
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

/**
 * Upload-or-URL logo field.
 *
 * One value, two entry paths: a URL typed into the input, or a file picked via
 * the upload button. An uploaded value is opaque (a data URI is not something
 * anyone edits by hand), so while one is set the URL input is replaced by a
 * preview row with Replace/Remove — clearing returns to the empty URL input.
 * Empty is a real state, not an error: it means "unbranded" at organization
 * level and "inherit" at school level.
 */
export function LogoInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [processing, setProcessing] = React.useState(false);
  const isUploaded = value.startsWith("data:image/");

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!file.type.startsWith("image/")) {
      setError("Choose an image file (PNG, JPEG, WebP or SVG).");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("That file is over 8 MB. Export the logo at a smaller size first.");
      return;
    }
    setProcessing(true);
    try {
      onChange(await fileToDataUri(file));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The image could not be processed.");
    } finally {
      setProcessing(false);
    }
  }

  return (
    <div className="grid gap-2">
      {/* The preview doubles as verification for BOTH paths: a pasted URL that
          renders proves it points at an image the browser can actually load. */}
      {value ? (
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- external or
              data URI at arbitrary origin; next/image needs configured hosts */}
          <img
            src={value}
            alt="Logo preview"
            className="h-12 w-12 rounded-md border border-border bg-background object-contain p-1"
          />
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            {isUploaded ? "Uploaded image" : value}
          </span>
          {!disabled ? (
            <button
              type="button"
              onClick={() => {
                onChange("");
                setError(null);
              }}
              className="rounded-sm p-1 text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
              <span className="sr-only">Remove logo</span>
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        {!isUploaded ? (
          <Input
            id={id}
            value={value}
            disabled={disabled}
            placeholder="https://…/logo.png"
            onChange={(event) => {
              setError(null);
              onChange(event.target.value);
            }}
          />
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || processing}
          onClick={() => fileInputRef.current?.click()}
          className="shrink-0"
        >
          <Upload className="size-4" aria-hidden />
          {processing ? "Processing…" : isUploaded ? "Replace image" : "Upload image"}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(event) => {
            void handleFile(event.target.files?.[0]);
            // Same file picked twice must fire change again (e.g. after Remove).
            event.target.value = "";
          }}
        />
      </div>

      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
