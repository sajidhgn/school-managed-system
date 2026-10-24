"use client";

import { Button } from "@heroui/react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { THEME_LABELS } from "@/components/marketing/picker-labels";
import { useTranslations } from "@/components/providers/i18n-provider";

const noSubscription = () => () => {};

/**
 * The header's theme button: a sun in light mode and a moon in dark, and pressing
 * it switches to the other. There is no System choice here, but a first visit
 * still follows the device (the provider's default) until the visitor presses it.
 *
 * The icon swaps on the `.dark` class alone, so it is right on the first paint.
 * The theme itself lives in localStorage, which the server cannot read, so until
 * hydration the button is named for what it is, not for what pressing it does.
 */
export function ThemeToggle() {
  const { locale } = useTranslations();
  const { resolvedTheme, setTheme } = useTheme();
  const hydrated = useSyncExternalStore(noSubscription, () => true, () => false);
  const labels = THEME_LABELS[locale];
  const dark = resolvedTheme === "dark";

  return (
    <Button
      isIconOnly
      variant="ghost"
      size="sm"
      aria-label={hydrated ? (dark ? labels.toLight : labels.toDark) : labels.label}
      onPress={() => setTheme(dark ? "light" : "dark")}
      className="text-mk-muted hover:text-mk-text"
    >
      <Sun className="dark:hidden" aria-hidden />
      <Moon className="hidden dark:block" aria-hidden />
    </Button>
  );
}
