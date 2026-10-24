import * as React from "react";

import { fieldClasses } from "@/components/ui/field-styles";
import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        fieldClasses,
        "flex h-9 px-3 py-1",
        "file:border-0 file:bg-transparent file:text-sm file:font-medium",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        fieldClasses,
        "flex min-h-20 px-3 py-2",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export { Input, Textarea };
