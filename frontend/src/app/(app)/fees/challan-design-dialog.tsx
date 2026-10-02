"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Plus, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { schools as schoolsApi } from "@/lib/api/resources";
import type {
  ChallanDesignConfig,
  ChallanPaymentAccount,
} from "@/lib/api/types";

/** A campus whose challan template this dialog edits. */
export interface ChallanSchool {
  id: string;
  name: string;
  challanDesign: ChallanDesignConfig | null;
}

/** The generated schema marks every knob optional (each has a server default). */
type ResolvedChallanDesign = Required<ChallanDesignConfig>;
type Copy = ResolvedChallanDesign["copies"][number];

const COPY_LABELS: [Copy, string][] = [
  ["bank", "Bank copy"],
  ["school", "School copy"],
  ["student", "Student copy"],
];

/**
 * Every knob's pre-feature value, mirroring `ChallanDesignConfig`'s defaults in
 * `backend/app/modules/tenancy/schemas.py`. A campus that never opened this
 * dialog has `challan_design: null`, and null must render identically to these
 * — otherwise saving anything at all would silently change the printed page.
 */
export const DEFAULT_CHALLAN_DESIGN: ResolvedChallanDesign = {
  copies: ["bank", "school", "student"],
  payment_accounts: [],
  show_admission_number: true,
  show_roll_number: true,
  show_father_name: true,
  show_contact: true,
  show_amount_in_words: true,
  show_signature_block: true,
  footer_note: "",
};

export function resolveChallanDesign(
  school: { challanDesign: ChallanDesignConfig | null } | null,
): ResolvedChallanDesign {
  return { ...DEFAULT_CHALLAN_DESIGN, ...(school?.challanDesign ?? {}) };
}

/**
 * The campus challan designer — the office's tool.
 *
 * =============================================================================
 * THE ACCOUNTS ARE THE REASON THIS SCREEN EXISTS
 * =============================================================================
 *   Everything else here is a preference. The account numbers are not: they are
 *   where a parent's money goes, printed on every challan this campus hands out.
 *   A stale number does not fail visibly — the transfer succeeds, into an account
 *   the school cannot reconcile, and it surfaces weeks later as a family insisting
 *   they paid. That is why they live on the school row, editable by the office,
 *   rather than anywhere a deployment is needed to correct them.
 *
 *   So the preview shows them exactly as they will print, at the top, the way a
 *   clerk reads them — the one check that catches a mistyped digit before four
 *   hundred challans carry it.
 */
export function ChallanDesignDialog({
  open,
  onOpenChange,
  school,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  school: ChallanSchool | null;
}) {
  const router = useRouter();
  const saved = React.useMemo(() => resolveChallanDesign(school), [school]);
  const [config, setConfig] = React.useState<ResolvedChallanDesign>(saved);
  const [saving, setSaving] = React.useState(false);

  // Re-sync after a save lands (router.refresh feeds new props down); also
  // discards stale edits if the template changed elsewhere.
  React.useEffect(() => setConfig(saved), [saved]);

  if (!school) return null;

  const set = <K extends keyof ChallanDesignConfig>(
    key: K,
    value: ResolvedChallanDesign[K],
  ) => setConfig((current) => ({ ...current, [key]: value }));

  function toggleCopy(copy: Copy, on: boolean) {
    const next = COPY_LABELS.map(([value]) => value).filter((value) =>
      value === copy ? on : config.copies.includes(value),
    );
    // At least one, matching the API's `min_length=1`: a challan with no copies is
    // a blank page, and letting it be saved turns every print into a support call.
    if (next.length === 0) return;
    set("copies", next);
  }

  function editAccount(index: number, patch: Partial<ChallanPaymentAccount>) {
    set(
      "payment_accounts",
      config.payment_accounts.map((account, i) =>
        i === index ? { ...account, ...patch } : account,
      ),
    );
  }

  async function save() {
    if (!school) return;
    setSaving(true);
    try {
      await schoolsApi.update(school.id, {
        challan_design: {
          ...config,
          // Half-typed rows are dropped rather than saved: an account with a label
          // and no number prints an empty "pay here" line, which is worse than no
          // line at all.
          payment_accounts: config.payment_accounts.filter(
            (account) => account.label.trim() && account.number.trim(),
          ),
        },
      });
      toast({ title: "Challan design saved for the whole campus." });
      router.refresh();
      onOpenChange(false);
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not save the challan design",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Challan design</DialogTitle>
          <DialogDescription>
            The printed fee challan for {school.name}. Saving applies it to
            every challan this campus prints from now on, including reprints of
            ones already issued.
          </DialogDescription>
        </DialogHeader>

        <section className="grid gap-2">
          <span className="text-xs text-muted-foreground">
            Copies printed on each page — the bank keeps one, stamps and returns
            one, and the parent keeps one
          </span>
          <div className="flex flex-wrap gap-4">
            {COPY_LABELS.map(([value, copyLabel]) => (
              <Toggle
                key={value}
                label={copyLabel}
                checked={config.copies.includes(value)}
                onChange={(on) => toggleCopy(value, on)}
              />
            ))}
          </div>
        </section>

        <section className="grid gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Accounts a parent may pay into — printed across the head of every
              copy
            </span>
            {config.payment_accounts.length < 4 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  set("payment_accounts", [
                    ...config.payment_accounts,
                    { label: "", number: "", holder: "" },
                  ])
                }
              >
                <Plus className="size-3.5" aria-hidden />
                Add account
              </Button>
            ) : null}
          </div>

          {config.payment_accounts.length === 0 ? (
            <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
              No accounts — the challan prints without a payment band, which is
              right for a campus that only takes cash at its own window.
            </p>
          ) : null}

          {config.payment_accounts.map((account, index) => (
            <div key={index} className="flex flex-wrap items-end gap-2">
              <Field
                label="Bank or wallet"
                value={account.label}
                placeholder="Meezan Bank"
                maxLength={60}
                onChange={(value) => editAccount(index, { label: value })}
              />
              <Field
                label="Account number"
                value={account.number}
                placeholder="98410113254130"
                maxLength={40}
                onChange={(value) => editAccount(index, { number: value })}
              />
              <Field
                label="Account title"
                value={account.holder ?? ""}
                placeholder="M. Aftab"
                maxLength={80}
                onChange={(value) => editAccount(index, { holder: value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8"
                title="Remove this account"
                onClick={() =>
                  set(
                    "payment_accounts",
                    config.payment_accounts.filter((_, i) => i !== index),
                  )
                }
              >
                <Trash2 className="size-4" aria-hidden />
                <span className="sr-only">Remove account {index + 1}</span>
              </Button>
            </div>
          ))}
        </section>

        <section className="grid gap-2">
          <span className="text-xs text-muted-foreground">
            Lines that print
          </span>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <Toggle
              label="Admission no."
              checked={config.show_admission_number}
              onChange={(v) => set("show_admission_number", v)}
            />
            <Toggle
              label="Roll no."
              checked={config.show_roll_number}
              onChange={(v) => set("show_roll_number", v)}
            />
            <Toggle
              label="Father / guardian"
              checked={config.show_father_name}
              onChange={(v) => set("show_father_name", v)}
            />
            <Toggle
              label="Contact number"
              checked={config.show_contact}
              onChange={(v) => set("show_contact", v)}
            />
            <Toggle
              label="Amount in words"
              checked={config.show_amount_in_words}
              onChange={(v) => set("show_amount_in_words", v)}
            />
            <Toggle
              label="Signature block"
              checked={config.show_signature_block}
              onChange={(v) => set("show_signature_block", v)}
            />
          </div>
        </section>

        <label className="grid gap-1 text-xs">
          <span className="text-muted-foreground">
            Footer line — leave empty for the standard &quot;quote the challan
            number&quot; wording
          </span>
          <input
            type="text"
            value={config.footer_note}
            onChange={(event) =>
              set("footer_note", event.target.value.slice(0, 200))
            }
            placeholder="Fees once paid are not refundable."
            className="h-8 rounded-md border border-input bg-card px-2 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>

        <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4">
          <p className="mb-3 text-center text-xs text-muted-foreground">
            Preview — sample student, one copy of {config.copies.length}
          </p>
          <ChallanPreview config={config} />
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button onClick={save} disabled={saving}>
            <Save className="size-4" aria-hidden />
            {saving ? "Saving…" : "Save design for campus"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The printed page, in HTML, at the proportions the PDF uses.
 *
 * A SECOND RENDERING OF THE SAME LAYOUT, and that is a real cost — the grid lives
 * in two languages and the two can drift. It is paid because the alternative is
 * worse: without a preview the only way to see a design decision is to save it to
 * the whole campus and print a real child's challan, which means every experiment
 * ships. The structure deliberately mirrors `challan_pdf.py` row for row so a
 * change there has an obvious counterpart here.
 */
function ChallanPreview({ config }: { config: ResolvedChallanDesign }) {
  const cell = "border border-black px-1.5 py-[3px] align-middle";
  const accounts = config.payment_accounts.filter(
    (account) => account.label.trim() && account.number.trim(),
  );

  return (
    <div className="overflow-x-auto">
      <table
        /* Sans, matching `_BODY_FACE` in challan_pdf.py. A preview set in a
           different face than the PDF is a preview that lies about line
           breaks, which is most of what this is here to show. */
        className="w-full min-w-[30rem] border-collapse bg-white font-sans text-[10px] text-black"
        aria-label="Challan preview"
      >
        <tbody>
          <tr>
            <td className={cell} style={{ width: "27%" }} />
            <td
              className={`${cell} text-center text-[13px] font-bold`}
              colSpan={4}
            >
              {COPY_LABELS.find(([value]) => value === config.copies[0])?.[1] ??
                "Copy"}
            </td>
            <td className={cell} style={{ width: "26%" }} />
          </tr>

          {accounts.map((account, index) => (
            <tr key={index}>
              <td className={`${cell} text-center font-bold`} colSpan={6}>
                Account Number ({account.label}) : {account.number}
                {account.holder ? ` (${account.holder})` : ""}
              </td>
            </tr>
          ))}

          <tr>
            <td className={`${cell} font-bold`} colSpan={3}>
              {config.show_admission_number ? (
                <div>
                  Admission No : <span className="font-normal">2026-042</span>
                </div>
              ) : null}
              {config.show_roll_number ? (
                <div>
                  Roll No : <span className="font-normal">10</span>
                </div>
              ) : null}
              <div>
                Session : <span className="font-normal">2026-2027</span>
              </div>
            </td>
            <td className={`${cell} font-bold`} colSpan={3}>
              Challan No : <span className="font-normal">FV-2026-00042</span>
            </td>
          </tr>

          <PreviewField label="Name" value="Aisha Khan" cell={cell} />
          {config.show_father_name ? (
            <PreviewField label="Father" value="Imran Khan" cell={cell} />
          ) : null}
          {config.show_contact ? (
            <PreviewField label="Contact" value="0300 1234567" cell={cell} />
          ) : null}

          <tr>
            <td className={`${cell} font-bold`}>Class</td>
            <td className={cell} colSpan={2}>
              Six
            </td>
            <td className={`${cell} font-bold`} colSpan={2}>
              Section
            </td>
            <td className={cell}>Jinnah</td>
          </tr>

          <tr>
            <td className={`${cell} font-bold`} colSpan={6}>
              Due Date: 10-Sep-2026 (Thursday)
            </td>
          </tr>

          <tr className="bg-neutral-200">
            <td className={`${cell} text-center font-bold`} colSpan={2}>
              Fee Month
            </td>
            <td className={`${cell} text-center font-bold`} colSpan={3}>
              Particular
            </td>
            <td className={`${cell} text-center font-bold`}>Payable (PKR)</td>
          </tr>

          {[
            ["Jul, 2026", "Tuition Fee", "1,700"],
            ["Aug, 2026", "Tuition Fee", "1,700"],
            ["Sep, 2026", "Tuition Fee", "1,700"],
          ].map(([month, particular, amount]) => (
            <tr key={month}>
              <td className={cell} colSpan={2}>
                {month}
              </td>
              <td className={cell} colSpan={3}>
                {particular}
              </td>
              <td className={`${cell} text-right`}>{amount}</td>
            </tr>
          ))}

          <tr className="bg-neutral-200">
            <td className={`${cell} text-center font-bold`} colSpan={5}>
              Total
            </td>
            <td className={`${cell} text-right font-bold`}>5,100</td>
          </tr>

          {config.show_amount_in_words ? (
            <tr>
              <td className={`${cell} font-bold`} colSpan={6}>
                Five Thousand One Hundred Only
              </td>
            </tr>
          ) : null}

          <PreviewPayable
            label="Payable Within Due Date"
            amount="5,100"
            cell={cell}
          />
          <PreviewPayable
            label="Payable After Due Date"
            amount="5,300"
            cell={cell}
          />

          <tr>
            <td className={cell} colSpan={6}>
              {config.show_signature_block ? (
                <div className="flex justify-between pb-6 font-bold">
                  <span>Received Amount By Officials:</span>
                  <span>Stamp &amp; Signature:</span>
                </div>
              ) : null}
              <div className="text-[9px]">
                {config.footer_note ||
                  "Please quote the challan number when paying. Keep the student copy as your receipt."}
              </div>
              <div className="flex justify-between text-[9px] font-bold">
                <span>
                  Printed at: <span className="font-normal">26-Aug-2026</span>
                </span>
                <span>
                  Printed By: <span className="font-normal">You</span>
                </span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function PreviewField({
  label,
  value,
  cell,
}: {
  label: string;
  value: string;
  cell: string;
}) {
  return (
    <tr>
      <td className={`${cell} font-bold`} colSpan={3}>
        {label}
      </td>
      <td className={cell} colSpan={3}>
        {value}
      </td>
    </tr>
  );
}

function PreviewPayable({
  label,
  amount,
  cell,
}: {
  label: string;
  amount: string;
  cell: string;
}) {
  return (
    <tr>
      <td className={`${cell} font-bold`} colSpan={4}>
        {label}
      </td>
      <td className={`${cell} text-right`} colSpan={2}>
        {amount}
      </td>
    </tr>
  );
}

function Field({
  label,
  value,
  placeholder,
  maxLength,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  maxLength: number;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-[8rem] flex-1 gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value.slice(0, maxLength))}
        className="h-8 rounded-md border border-input bg-card px-2 text-xs shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </label>
  );
}

function Toggle({
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
