"use client";

import * as React from "react";
import { FileText, Loader2, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACCEPTED_FILES = "application/pdf,image/jpeg,image/png,image/webp";
/** The API reads at most 10 files (and 16 pages) per reading. */
export const MAX_SCAN_FILES = 10;

/**
 * Step one of "Read with AI": choose photos or a PDF of the book's cover and
 * contents pages. The dialog sends them; this panel only collects them.
 */
export function BookScanPanel({
  files,
  onFilesChange,
  reading,
}: {
  files: File[];
  onFilesChange: (files: File[]) => void;
  reading: boolean;
}) {
  const input = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);

  const add = (picked: FileList | null) => {
    const known = new Set(files.map(fileKey));
    const fresh = Array.from(picked ?? []).filter((f) => !known.has(fileKey(f)));
    if (fresh.length) onFilesChange([...files, ...fresh].slice(0, MAX_SCAN_FILES));
  };

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={reading ? -1 : 0}
        aria-disabled={reading}
        onClick={() => !reading && input.current?.click()}
        onKeyDown={(event) => {
          if (!reading && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!reading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!reading) add(event.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm transition-colors hover:bg-accent/50",
          dragging && "border-primary bg-primary/5",
          reading && "pointer-events-none opacity-60",
        )}
      >
        {reading ? (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        ) : (
          <Upload className="size-5 text-muted-foreground" />
        )}
        <span className="font-medium">
          {reading ? "Reading the pages…" : "Upload the cover and contents pages"}
        </span>
        <span className="max-w-md text-xs text-muted-foreground">
          {reading
            ? "The AI is reading the title, publisher, edition, class, subject and chapter list. This can take up to a minute."
            : "Photos (JPEG, PNG or WebP) or a PDF of the book. Include the cover, the page with the edition and publisher, and every contents page. Drop files here or click to choose."}
        </span>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED_FILES}
          className="hidden"
          onChange={(event) => {
            add(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {files.map((file) => (
            <li
              key={fileKey(file)}
              className="flex min-w-0 items-center gap-2 rounded-md border border-border p-1.5 text-sm"
            >
              <FileThumb file={file} />
              <span className="min-w-0 flex-1 truncate" title={file.name}>
                {file.name}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${file.name}`}
                disabled={reading}
                onClick={() => onFilesChange(files.filter((f) => f !== file))}
              >
                <X />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {files.length >= MAX_SCAN_FILES && (
        <p className="text-xs text-muted-foreground">
          {MAX_SCAN_FILES} files at most — the cover and the contents pages are enough.
        </p>
      )}
    </div>
  );
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

/** A small preview of a chosen photo, so the teacher can see it is the cover. */
function FileThumb({ file }: { file: File }) {
  const [url, setUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!file.type.startsWith("image/")) return;
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  if (!url) {
    return (
      <span className="flex size-10 shrink-0 items-center justify-center rounded bg-muted">
        <FileText className="size-4 text-muted-foreground" />
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element -- a local blob: preview
  return <img src={url} alt="" className="size-10 shrink-0 rounded object-cover" />;
}
