"use client";

import { ToggleButton, ToggleButtonGroup } from "@heroui/react";

import { useLocaleChoice } from "@/components/locale-switcher";
import { LANGUAGE_LABEL, LANGUAGE_NAMES } from "@/components/marketing/picker-labels";
import { LOCALES } from "@/lib/i18n/config";

/**
 * Both languages side by side, the current one pressed: the footer's and the
 * mobile menu's picker, where a menu inside a menu would be one tap too many.
 */
export function LocaleToggle({ className }: { className?: string }) {
  const { locale, pending, select } = useLocaleChoice();

  return (
    <ToggleButtonGroup
      aria-label={LANGUAGE_LABEL[locale]}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[locale]}
      onSelectionChange={(keys) => {
        const next = [...keys][0];
        if (next && next !== locale) select(String(next));
      }}
      isDisabled={pending}
      size="sm"
      className={className}
    >
      {LOCALES.map((code) => (
        <ToggleButton key={code} id={code}>
          {LANGUAGE_NAMES[locale][code]}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
