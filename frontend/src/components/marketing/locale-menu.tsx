"use client";

import { Button, Dropdown, Label } from "@heroui/react";
import { Languages } from "lucide-react";

import { useLocaleChoice } from "@/components/locale-switcher";
import { LANGUAGE_LABEL, LANGUAGE_NAMES } from "@/components/marketing/picker-labels";
import { LOCALES } from "@/lib/i18n/config";

/**
 * The header's language picker: the current language, opening a menu of both.
 * Names are in the page's language (picker-labels.ts), so the translate icon
 * is what marks it as the picker to someone who cannot read them.
 */
export function LocaleMenu() {
  const { locale, pending, select } = useLocaleChoice();
  const names = LANGUAGE_NAMES[locale];

  return (
    <Dropdown>
      <Button variant="ghost" size="sm" isDisabled={pending} className="text-mk-muted hover:text-mk-text">
        <Languages className="size-4" aria-hidden />
        {names[locale]}
      </Button>
      <Dropdown.Popover placement="bottom end">
        <Dropdown.Menu
          aria-label={LANGUAGE_LABEL[locale]}
          selectionMode="single"
          disallowEmptySelection
          selectedKeys={new Set([locale])}
          onSelectionChange={(keys) => {
            const next = keys === "all" ? undefined : [...keys][0];
            if (next && next !== locale) select(String(next));
          }}
        >
          {LOCALES.map((code) => (
            <Dropdown.Item key={code} id={code} textValue={names[code]}>
              <Dropdown.ItemIndicator />
              <Label>{names[code]}</Label>
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
