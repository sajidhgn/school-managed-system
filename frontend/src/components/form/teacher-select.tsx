"use client";

import * as React from "react";
import Select, { components, type GroupBase, type OptionProps, type SingleValue } from "react-select";
import { Check, ChevronDown, X } from "lucide-react";

import { useTeachers } from "@/hooks/use-members";
import { SELECT_MENU_CLASS } from "@/components/form/select-portal";
import type { TeacherOption as TeacherOptionDto } from "@/lib/api/types";

/**
 * Class-teacher picker: the branch's teaching staff, searchable by name or email.
 *
 * =============================================================================
 * WHY THIS REPLACED A TEXT INPUT
 * =============================================================================
 *   The field used to be "Class teacher ID -- paste the teacher's user ID". That
 *   asked an administrator to go and find a UUID, and it made the two most likely
 *   mistakes indistinguishable from success: a typo'd id is rejected by the server as
 *   a foreign key violation, and a VALID id belonging to the wrong person is accepted
 *   silently. Choosing from a list removes both -- you cannot name someone who is not
 *   on staff at this campus, and you pick a human by their name.
 *
 * =============================================================================
 * THE LIST IS BUILT SERVER-SIDE, AND THAT IS THE POINT
 * =============================================================================
 *   `GET /schools/{id}/teachers` decides who counts as a teacher, by asking which
 *   roles grant the teaching permissions. Doing it here would mean shipping every
 *   role's permission set to the browser and re-implementing that rule in TypeScript,
 *   where it would drift from the Python one. See `TEACHING_PERMISSIONS`.
 *
 * =============================================================================
 * PORTALLED MENU: NOT A STYLE CHOICE
 * =============================================================================
 *   `DialogContent` is `overflow-y-auto` AND carries a `-translate-*` transform. The
 *   overflow clips an inline menu; the transform makes the dialog a containing block,
 *   so `position: fixed` is clipped by it too. Rendering into `document.body` is the
 *   only placement that escapes both -- and because Radix sets `pointer-events: none`
 *   on the body while a modal is open, the portal has to hand them back explicitly or
 *   every option is unclickable.
 */

/** What react-select actually holds. `value` is a user id -- see below. */
type Option = {
  value: string;
  label: string;
  email: string;
  roleName: string;
  /** True for the placeholder we synthesise for an assignee who has left the list. */
  stale?: boolean;
};

function toOption(teacher: TeacherOptionDto): Option {
  return {
    value: teacher.user_id,
    label: teacher.full_name,
    email: teacher.email,
    roleName: teacher.role_name,
  };
}

/**
 * Name on top, email and role beneath.
 *
 * The second line is not decoration. Staff lists genuinely contain two people called
 * the same thing -- this project's own seed data has two Kamran Tariqs on one campus
 * -- and a picker that renders both as an identical row is a coin flip that assigns
 * someone's class to a stranger.
 */
function TeacherOptionRow(props: OptionProps<Option, false, GroupBase<Option>>) {
  const { data, isSelected } = props;
  return (
    <components.Option {...props}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{data.label}</div>
          <div className="truncate text-xs text-muted-foreground">
            {data.stale ? "No longer teaching staff at this campus" : `${data.email} · ${data.roleName}`}
          </div>
        </div>
        {isSelected ? <Check className="mt-0.5 size-4 shrink-0" aria-hidden /> : null}
      </div>
    </components.Option>
  );
}

export function TeacherSelect({
  schoolId,
  value,
  onChange,
  onBlur,
  id,
  disabled,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
}: {
  schoolId: string | null;
  /** A user id, or "" / null for "no class teacher". */
  value: string | null;
  onChange: (userId: string) => void;
  onBlur?: () => void;
  id?: string;
  disabled?: boolean;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  const { data, isLoading, isError } = useTeachers(schoolId);

  const options = React.useMemo<Option[]>(() => (data ?? []).map(toOption), [data]);

  // An already-assigned teacher who is no longer IN the list -- suspended, moved
  // campus, or moved to a role that does not teach. Without this the select would
  // render empty, which reads as "no class teacher" and would silently clear a real
  // assignment the moment the form is saved. Showing them, labelled, keeps the edit
  // honest: you can leave them or replace them, but you are never lied to.
  const selected = React.useMemo<Option | null>(() => {
    if (!value) return null;
    const match = options.find((o) => o.value === value);
    if (match) return match;
    if (isLoading || isError) return null;
    return { value, label: "Assigned teacher", email: "", roleName: "", stale: true };
  }, [value, options, isLoading, isError]);

  const optionsWithStale = React.useMemo<Option[]>(
    () => (selected?.stale ? [selected, ...options] : options),
    [selected, options],
  );

  return (
    <Select<Option, false>
      // Stable across server and client render: react-select otherwise generates a
      // fresh id each time and React reports a hydration mismatch.
      instanceId={id ?? "class-teacher"}
      inputId={id}
      aria-invalid={ariaInvalid}
      aria-describedby={ariaDescribedBy}
      unstyled
      isClearable
      isSearchable
      isLoading={isLoading}
      isDisabled={disabled || !schoolId}
      options={optionsWithStale}
      value={selected}
      onBlur={onBlur}
      onChange={(next: SingleValue<Option>) => onChange(next?.value ?? "")}
      // Search matches the email too, so an administrator who knows the address but
      // not the spelling of the name still lands on the right person.
      filterOption={(candidate, raw) => {
        const needle = raw.trim().toLowerCase();
        if (!needle) return true;
        const { label, email, roleName } = candidate.data as Option;
        return `${label} ${email} ${roleName}`.toLowerCase().includes(needle);
      }}
      placeholder={schoolId ? "Search staff by name or email…" : "Select a campus first"}
      loadingMessage={() => "Loading teaching staff…"}
      noOptionsMessage={() =>
        isError
          ? "Couldn't load teaching staff."
          : "No teaching staff at this campus yet. Invite a teacher first."
      }
      components={{
        Option: TeacherOptionRow,
        IndicatorSeparator: null,
        DropdownIndicator: (props) => (
          <components.DropdownIndicator {...props}>
            <ChevronDown className="size-4 opacity-50" aria-hidden />
          </components.DropdownIndicator>
        ),
        ClearIndicator: (props) => (
          <components.ClearIndicator {...props}>
            <X className="size-4 opacity-50 hover:opacity-100" aria-hidden />
          </components.ClearIndicator>
        ),
      }}
      // See the header: body is the only target that escapes the dialog's clipping.
      menuPortalTarget={typeof document === "undefined" ? undefined : document.body}
      menuPlacement="auto"
      styles={{
        // The one place raw styles are unavoidable -- z-index and pointer-events have
        // to beat Radix's modal, which sets them as inline/overlay styles of its own.
        menuPortal: (base) => ({ ...base, zIndex: 60, pointerEvents: "auto" }),
      }}
      classNames={{
        control: ({ isFocused, isDisabled }) =>
          [
            "flex min-h-9 w-full items-center gap-2 rounded-md border bg-card px-3 py-1 text-sm shadow-sm",
            isFocused ? "ring-2 ring-ring ring-offset-1 ring-offset-background" : "",
            ariaInvalid ? "border-destructive" : "border-input",
            isDisabled ? "cursor-not-allowed opacity-50" : "",
          ].join(" "),
        valueContainer: () => "flex flex-wrap gap-1 py-0.5",
        placeholder: () => "text-muted-foreground",
        singleValue: () => "text-foreground",
        input: () => "text-foreground [&_input:focus]:ring-0",
        indicatorsContainer: () => "flex items-center gap-1",
        clearIndicator: () => "cursor-pointer p-0.5",
        dropdownIndicator: () => "p-0.5",
        loadingIndicator: () => "pe-1 text-muted-foreground",
        // SELECT_MENU_CLASS is load-bearing, not cosmetic: it is how the dialog
        // recognises a click in here as "inside" and does not dismiss itself.
        menu: () =>
          `${SELECT_MENU_CLASS} z-50 mt-1 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md`,
        menuList: () => "max-h-64 overflow-y-auto p-1",
        option: ({ isFocused, isSelected }) =>
          [
            "cursor-default select-none rounded-sm px-2 py-1.5 text-sm outline-none",
            isFocused ? "bg-accent text-accent-foreground" : "",
            isSelected && !isFocused ? "font-medium" : "",
          ].join(" "),
        noOptionsMessage: () => "px-2 py-6 text-center text-sm text-muted-foreground",
        loadingMessage: () => "px-2 py-6 text-center text-sm text-muted-foreground",
      }}
    />
  );
}
