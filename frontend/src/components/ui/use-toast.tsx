"use client";

import * as React from "react";

import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast";

/**
 * Minimal toast store.
 *
 * Deliberately small: a queue in React state plus a module-level emitter, so
 * `toast()` can be called from mutation callbacks that have no component
 * context.
 */

type Variant = "default" | "success" | "destructive";

interface ToastItem {
  id: string;
  title?: string;
  description?: string;
  variant?: Variant;
}

type Listener = (toasts: ToastItem[]) => void;

let toasts: ToastItem[] = [];
const listeners = new Set<Listener>();
let counter = 0;

function emit() {
  for (const listener of listeners) listener([...toasts]);
}

export function toast(input: Omit<ToastItem, "id">) {
  const id = `t${++counter}`;
  toasts = [...toasts, { ...input, id }];
  emit();
  return id;
}

toast.success = (title: string, description?: string) =>
  toast({ title, description, variant: "success" });

toast.error = (title: string, description?: string) =>
  toast({ title, description, variant: "destructive" });

function dismiss(id: string) {
  toasts = toasts.filter((item) => item.id !== id);
  emit();
}

export function Toaster() {
  const [items, setItems] = React.useState<ToastItem[]>([]);

  React.useEffect(() => {
    listeners.add(setItems);
    setItems([...toasts]);
    return () => {
      listeners.delete(setItems);
    };
  }, []);

  return (
    <ToastProvider swipeDirection="right">
      {items.map(({ id, title, description, variant }) => (
        <Toast
          key={id}
          variant={variant}
          duration={variant === "destructive" ? 8000 : 4000}
          onOpenChange={(open) => {
            if (!open) dismiss(id);
          }}
        >
          <div className="grid gap-1">
            {title ? <ToastTitle>{title}</ToastTitle> : null}
            {description ? <ToastDescription>{description}</ToastDescription> : null}
          </div>
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
