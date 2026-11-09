"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { NativeSelect } from "@/components/ui/native-select";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { schools as schoolsApi } from "@/lib/api/resources";
import type { StudentListRow } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { studentsCardMessages } from "@/lib/i18n/modules/students-card";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn } from "@/lib/utils";
import {
  CARD_DESIGNS,
  CardBackdrop,
  StudentCardBackView,
  StudentCardView,
  designTokens,
  resolveCardDesign,
  resolvePalette,
  type CardSchool,
  type ResolvedCardDesign,
} from "./student-card";

/**
 * The preview wears a made-up child, never a real one. The designer is opened
 * by admins whose screen may be visible at a counter, and a real student's
 * guardian phone number has no business being the demo. Every printable field
 * is filled so toggles visibly do something.
 */
const SAMPLE_STUDENT: StudentListRow = {
  id: "00000000-0000-0000-0000-000000000000",
  admission_number: "2026-042",
  first_name: "Aisha",
  last_name: "Khan",
  full_name: "Aisha Khan",
  date_of_birth: "2015-03-14",
  gender: null,
  address: null,
  photo_url: null,
  guardian_name: "Imran Khan",
  guardian_phone: "0300 1234567",
  guardian_email: null,
  emergency_contact_name: "Sana Khan",
  emergency_contact_phone: "0301 7654321",
  section_id: null,
  class_name: "Grade 5",
  section_name: "B",
  status: "active",
  enrolled_on: "2026-04-01",
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
  dues: null,
};

/**
 * The campus card designer — the principal's tool.
 *
 * All the template's options live HERE, once per school, not on any individual
 * student's card: design, orientation, logo and photo placement, photo frame,
 * which fields print, whose number the contact line shows, whether the QR
 * prints. Saving writes the template to the school, and every "View card" in
 * the students table renders it from then on — the cards in one school bag
 * all match.
 */
export function CardDesignDialog({
  open,
  onOpenChange,
  school,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  school: CardSchool | null;
}) {
  const m = useCatalog(studentsCardMessages).designer;
  const router = useRouter();
  const savedDesign = React.useMemo(() => resolveCardDesign(school), [school]);
  const [config, setConfig] = React.useState<ResolvedCardDesign>(savedDesign);
  const [saving, setSaving] = React.useState(false);

  // The textarea holds the text as typed (blank lines and all) while the
  // config holds the cleaned list — otherwise pressing Enter twice would
  // fight the cleaning and the caret would jump.
  const [rulesText, setRulesText] = React.useState(savedDesign.rules.join("\n"));

  // Re-sync after a save lands (router.refresh feeds new props down); also
  // discards stale edits if the template changed elsewhere.
  React.useEffect(() => {
    setConfig(savedDesign);
    setRulesText(savedDesign.rules.join("\n"));
  }, [savedDesign]);

  if (!school) return null;

  const set = <K extends keyof ResolvedCardDesign>(key: K, value: ResolvedCardDesign[K]) =>
    setConfig((current) => ({ ...current, [key]: value }));

  function changeRules(text: string) {
    setRulesText(text);
    // Mirror the API's caps (six lines of 120) so a save never 422s.
    set(
      "rules",
      text
        .split("\n")
        .map((line) => line.trim().slice(0, 120))
        .filter(Boolean)
        .slice(0, 6),
    );
  }

  async function save() {
    if (!school) return;
    setSaving(true);
    try {
      await schoolsApi.update(school.id, { card_design: config });
      toast({ title: m.saved });
      router.refresh();
      onOpenChange(false);
    } catch (error) {
      toast({
        variant: "destructive",
        title: m.saveFailed,
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  const palette = resolvePalette(school);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{m.title}</DialogTitle>
          <DialogDescription>{fill(m.description, { school: school.name })}</DialogDescription>
        </DialogHeader>

        <div
          role="radiogroup"
          aria-label={m.gallery}
          className="flex max-h-56 flex-wrap justify-center gap-3 overflow-y-auto rounded-md border border-border/60 p-2"
        >
          {CARD_DESIGNS.map((value) => (
            <DesignThumbnail
              key={value}
              design={value}
              palette={palette}
              selected={config.design === value}
              onSelect={() => set("design", value)}
            />
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <DesignerSelect
            label={m.orientation}
            value={config.orientation}
            onChange={(v) => set("orientation", v as ResolvedCardDesign["orientation"])}
            options={[
              ["landscape", m.landscape],
              ["portrait", m.portrait],
            ]}
          />
          <DesignerSelect
            label={m.logoPosition}
            value={config.logo_position}
            onChange={(v) => set("logo_position", v as ResolvedCardDesign["logo_position"])}
            options={[
              ["start", m.logoStart],
              ["center", m.logoCenter],
              ["end", m.logoEnd],
            ]}
          />
          <DesignerSelect
            label={m.contactNumber}
            value={config.contact_number}
            onChange={(v) => set("contact_number", v as ResolvedCardDesign["contact_number"])}
            options={[
              ["guardian", m.contactGuardian],
              ["emergency", m.contactEmergency],
              ["school", m.contactSchool],
            ]}
          />
          <DesignerSelect
            label={m.photoShape}
            value={config.photo_shape}
            onChange={(v) => set("photo_shape", v as ResolvedCardDesign["photo_shape"])}
            options={[
              ["rounded", m.shapeRounded],
              ["circle", m.shapeCircle],
              ["square", m.shapeSquare],
            ]}
          />
          <DesignerSelect
            label={m.photoSize}
            value={config.photo_size}
            onChange={(v) => set("photo_size", v as ResolvedCardDesign["photo_size"])}
            options={[
              ["sm", m.sizeSm],
              ["md", m.sizeMd],
              ["lg", m.sizeLg],
            ]}
          />
          <DesignerSelect
            label={m.photoSide}
            value={config.photo_position}
            onChange={(v) => set("photo_position", v as ResolvedCardDesign["photo_position"])}
            options={[
              ["start", m.photoStart],
              ["end", m.photoEnd],
            ]}
          />
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <DesignerToggle
            label={m.showAdmissionNo}
            checked={config.show_admission_number}
            onChange={(v) => set("show_admission_number", v)}
          />
          <DesignerToggle
            label={m.showClass}
            checked={config.show_class}
            onChange={(v) => set("show_class", v)}
          />
          <DesignerToggle
            label={m.showDateOfBirth}
            checked={config.show_date_of_birth}
            onChange={(v) => set("show_date_of_birth", v)}
          />
          <DesignerToggle
            label={m.showGuardianName}
            checked={config.show_guardian_name}
            onChange={(v) => set("show_guardian_name", v)}
          />
          <DesignerToggle
            label={m.showQr}
            checked={config.show_qr}
            onChange={(v) => set("show_qr", v)}
          />
          <DesignerToggle
            label={m.showValidity}
            checked={config.show_validity}
            onChange={(v) => set("show_validity", v)}
          />
        </div>

        <div className="grid gap-1 text-xs">
          <span className="text-muted-foreground">{m.rulesLabel}</span>
          <textarea
            value={rulesText}
            onChange={(event) => changeRules(event.target.value)}
            rows={3}
            placeholder={m.rulesPlaceholder}
            className="rounded-control border border-input bg-card px-2 py-1.5 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="grid gap-1 text-xs">
          <span className="text-muted-foreground">{m.contactLineLabel}</span>
          <input
            type="text"
            value={config.contact_line}
            onChange={(event) => set("contact_line", event.target.value.slice(0, 120))}
            placeholder={m.contactLinePlaceholder}
            className="h-8 rounded-control border border-input bg-card px-2 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="grid gap-1 text-xs">
          <span className="text-muted-foreground">{m.foundNoticeLabel}</span>
          <textarea
            value={config.found_notice}
            onChange={(event) => set("found_notice", event.target.value.slice(0, 300))}
            rows={2}
            placeholder={m.foundNoticePlaceholder}
            className="rounded-control border border-input bg-card px-2 py-1.5 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4">
          <p className="mb-3 text-center text-xs text-muted-foreground">{m.previewFront}</p>
          <StudentCardView student={SAMPLE_STUDENT} school={school} config={config} />
          <p className="my-3 text-center text-xs text-muted-foreground">{m.previewBack}</p>
          <StudentCardBackView student={SAMPLE_STUDENT} school={school} config={config} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {m.cancel}
          </Button>
          <Button onClick={save} disabled={saving}>
            <Save className="size-4" aria-hidden />
            {saving ? m.saving : m.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DesignerSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [value: string, label: string][];
}) {
  return (
    <label className="grid gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <NativeSelect value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </NativeSelect>
    </label>
  );
}

function DesignerToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-3.5 accent-primary"
      />
      {label}
    </label>
  );
}

/**
 * A clickable miniature of one design, drawn with the school's real palette so
 * the gallery previews THIS school's cards, not a stock screenshot's.
 */
function DesignThumbnail({
  design,
  palette,
  selected,
  onSelect,
}: {
  design: ResolvedCardDesign["design"];
  palette: string[];
  selected: boolean;
  onSelect: () => void;
}) {
  const designLabels: Record<ResolvedCardDesign["design"], string> =
    useCatalog(studentsCardMessages).designs;
  const tokens = designTokens(design, palette);
  const headerBand = tokens.headerStyle?.backgroundColor || tokens.headerStyle?.backgroundImage;

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className="flex flex-col items-center gap-1"
    >
      <span
        className={cn(
          // The CR80 aspect ratio, so the miniature is honest about proportions.
          "relative block h-12 w-[76px] overflow-hidden rounded border-2 bg-card transition-shadow",
          selected ? "border-primary ring-2 ring-primary/40" : "border-border hover:border-primary/50",
        )}
        style={design === "bold" ? { borderColor: tokens.cardStyle?.borderColor } : undefined}
      >
        {headerBand ? (
          <span
            className="absolute inset-x-0 top-0 h-3"
            style={{
              backgroundColor: tokens.headerStyle?.backgroundColor,
              backgroundImage: tokens.headerStyle?.backgroundImage,
            }}
          />
        ) : (
          <span className="absolute inset-x-0 top-3 border-t border-border" />
        )}
        {tokens.footerStyle?.backgroundColor ? (
          <span
            className="absolute inset-x-0 bottom-0 h-2"
            style={{ backgroundColor: tokens.footerStyle.backgroundColor }}
          />
        ) : null}
        {tokens.stripeColor ? (
          <span
            className="absolute inset-y-0 start-0 w-1"
            style={{ backgroundColor: tokens.stripeColor }}
          />
        ) : null}
        {tokens.sweep ? (
          <span
            className={cn(
              "absolute inset-y-0 w-4",
              (tokens.sweep.edge ?? "start") === "start" ? "start-0" : "end-0",
            )}
            style={{
              background: tokens.sweep.background,
              ...((tokens.sweep.edge ?? "start") === "start"
                ? { borderStartEndRadius: "60% 45%", borderEndEndRadius: "85% 70%" }
                : { borderStartStartRadius: "60% 45%", borderEndStartRadius: "85% 70%" }),
            }}
          />
        ) : null}
        {/* Percentage-sized, so the real backdrop decorates the miniature. */}
        <CardBackdrop backdrop={tokens.backdrop} />
        {tokens.panel ? (
          // The photo panel replaces the photo box on the trailing edge.
          <span
            className={cn(
              "absolute inset-y-0 end-0 w-5",
              tokens.panel.clip === "chevron" &&
                "[clip-path:polygon(32%_0,100%_0,100%_100%,32%_100%,0_50%)]",
            )}
            style={{ backgroundColor: tokens.panel.background }}
          />
        ) : (
          <span className="absolute start-2 top-4.5 block h-5 w-4 rounded-[2px] border border-border bg-muted" />
        )}
        {/* The card's anatomy in miniature: name line and a detail line, the
            latter wearing its icon chip on the chip designs. */}
        <span
          className={cn(
            "absolute top-5 block h-1 w-9 rounded-full bg-foreground/60",
            tokens.panel ? "start-2" : "start-7",
          )}
        />
        {tokens.chips ? (
          <span
            className={cn(
              "absolute top-7 block h-1.5",
              tokens.panel ? "start-2" : "start-7",
              tokens.chips.shape === "arrow"
                ? "w-3 [clip-path:polygon(0_0,72%_0,100%_50%,72%_100%,0_100%)]"
                : "w-1.5 rounded-full",
            )}
            style={{ backgroundColor: tokens.chips.background }}
          />
        ) : (
          <span className="absolute start-7 top-7 block h-1 w-6 rounded-full bg-muted-foreground/50" />
        )}
      </span>
      <span
        className={cn(
          "text-[11px]",
          selected ? "font-medium text-foreground" : "text-muted-foreground",
        )}
      >
        {designLabels[design]}
      </span>
    </button>
  );
}
