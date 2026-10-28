"use client";

import * as React from "react";
import { skeletonVariants } from "@heroui/styles";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/utils";

// --- Avatar ----------------------------------------------------------------

const Avatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn("relative flex size-8 shrink-0 overflow-hidden rounded-full", className)}
    {...props}
  />
));
Avatar.displayName = AvatarPrimitive.Root.displayName;

const AvatarImage = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Image>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Image ref={ref} className={cn("aspect-square size-full", className)} {...props} />
));
AvatarImage.displayName = AvatarPrimitive.Image.displayName;

const AvatarFallback = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Fallback>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Fallback
    ref={ref}
    className={cn(
      "flex size-full items-center justify-center rounded-full bg-accent text-xs font-medium text-accent-foreground",
      className,
    )}
    {...props}
  />
));
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName;

// --- Separator -------------------------------------------------------------

const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(({ className, orientation = "horizontal", decorative = true, ...props }, ref) => (
  <SeparatorPrimitive.Root
    ref={ref}
    decorative={decorative}
    orientation={orientation}
    className={cn(
      "shrink-0 bg-border",
      orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
      className,
    )}
    {...props}
  />
));
Separator.displayName = SeparatorPrimitive.Root.displayName;

// --- Tabs ------------------------------------------------------------------

const Tabs = TabsPrimitive.Root;

/**
 * HeroUI's segmented tabs: a gray track with a white pill that slides to the
 * selected tab.
 *
 * Radix does not say where its tabs are, so the list measures the active one and
 * moves the pill there, re-measuring whenever a tab's `data-state` changes or the
 * list resizes. Offsets are physical (`offsetLeft` from the list's left edge), so
 * the pill lands correctly under RTL without a mirrored rule.
 *
 * Until that first measurement the active tab paints its own white fill, so the
 * selection is visible before hydration; `data-ready` hands the job to the pill.
 *
 * The tabs and the pill take the control radius; the track adds its 4px padding
 * to that, so the corners stay concentric.
 */
const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, children, ...props }, forwardedRef) => {
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const [pill, setPill] = React.useState<{ left: number; width: number } | null>(null);

  const setRefs = React.useCallback(
    (node: HTMLDivElement | null) => {
      listRef.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    },
    [forwardedRef],
  );

  React.useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const measure = () => {
      const active = list.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
      setPill(active ? { left: active.offsetLeft, width: active.offsetWidth } : null);
    };
    measure();
    const mutations = new MutationObserver(measure);
    mutations.observe(list, { subtree: true, attributes: true, attributeFilter: ["data-state"] });
    const resizes = new ResizeObserver(measure);
    resizes.observe(list);
    return () => {
      mutations.disconnect();
      resizes.disconnect();
    };
  }, []);

  return (
    <TabsPrimitive.List
      ref={setRefs}
      data-ready={pill ? "true" : undefined}
      className={cn(
        "group/tabs relative inline-flex h-10 items-center justify-center rounded-[calc(var(--control-radius)+4px)] bg-[var(--default)] p-1 text-muted-foreground",
        className,
      )}
      {...props}
    >
      {pill ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-1 left-0 rounded-control bg-card shadow-[0_1px_2px_0_rgb(10_12_16/0.08),0_0_1px_0_rgb(10_12_16/0.1)] transition-[transform,width] duration-300 ease-fluid"
          style={{ width: pill.width, transform: `translateX(${pill.left}px)` }}
        />
      ) : null}
      {children}
    </TabsPrimitive.List>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "relative z-10 inline-flex h-8 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-control px-4 text-sm font-medium",
      "transition-[color,transform] duration-150 ease-out hover:text-foreground active:scale-[0.97]",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
      "data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm",
      "group-data-[ready=true]/tabs:data-[state=active]:bg-transparent group-data-[ready=true]/tabs:data-[state=active]:shadow-none",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-4 focus-visible:outline-none data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:duration-300",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

// --- Skeleton --------------------------------------------------------------

/** HeroUI's skeleton: a gray block with a highlight sweeping across it. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn(skeletonVariants().base(), "rounded-md", className)} {...props} />;
}

export {
  Avatar,
  AvatarImage,
  AvatarFallback,
  Separator,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Skeleton,
};
