"use client";

import { Eye, EyeOff } from "lucide-react";
import * as React from "react";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * A password field you can read back.
 *
 * WHY THIS EXISTS
 *   Passphrases are what this product asks for — "at least 10 characters, a phrase
 *   of unrelated words works best" — and a long phrase typed blind on a phone
 *   keyboard is the single most common way a correct password gets rejected. The
 *   toggle turns "wrong password" into "I can see the typo".
 *
 * IT IS ALWAYS A REAL `type="password"` WHEN HIDDEN
 *   Not a text input with a masking font. Password managers, autofill and the
 *   browser's own "save this?" prompt all key off the real type, and `autoComplete`
 *   is passed through untouched, so revealing the value never costs the user their
 *   saved credential.
 *
 * ACCESSIBILITY
 *   `type="button"`, so pressing it never submits the form — the classic bug with
 *   an unmarked button inside a form. It is deliberately IN the tab order, because
 *   somebody navigating by keyboard is exactly who needs to check what they typed;
 *   `aria-pressed` reports the current state, and the label says what activating it
 *   will do next.
 *
 *   Positioned with `end-0`/`pe-9` rather than `right-0`/`pr-9` so it moves to the
 *   other side under RTL, where this app genuinely runs (Urdu).
 *
 * `Field` clones its child to inject `id`, `aria-invalid` and `aria-describedby`,
 * so those arrive here as ordinary props and are spread onto the real input. Drop
 * this in wherever `<Input type="password" />` was and the wiring survives.
 */
export const PasswordInput = React.forwardRef<
  HTMLInputElement,
  Omit<React.ComponentProps<"input">, "type"> & {
    /** For surfaces that are not the app's own palette — the dark platform console. */
    toggleClassName?: string;
  }
>(({ className, toggleClassName, disabled, ...props }, ref) => {
  const { t } = useTranslations();
  const [revealed, setRevealed] = React.useState(false);

  return (
    <div className="relative">
      <Input
        {...props}
        ref={ref}
        disabled={disabled}
        type={revealed ? "text" : "password"}
        className={cn("pe-9", className)}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => setRevealed((current) => !current)}
        aria-pressed={revealed}
        aria-label={revealed ? t.auth.hidePassword : t.auth.showPassword}
        title={revealed ? t.auth.hidePassword : t.auth.showPassword}
        className={cn(
          "absolute inset-y-0 end-0 grid w-9 place-items-center rounded-e-md text-muted-foreground",
          "transition-colors hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "disabled:cursor-not-allowed disabled:opacity-50",
          toggleClassName,
        )}
      >
        {revealed ? (
          <EyeOff className="size-4" aria-hidden />
        ) : (
          <Eye className="size-4" aria-hidden />
        )}
      </button>
    </div>
  );
});
PasswordInput.displayName = "PasswordInput";
