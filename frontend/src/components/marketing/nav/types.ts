import {
  BadgeCheck,
  Building2,
  CalendarCheck,
  CircleHelp,
  CirclePlay,
  CreditCard,
  FileText,
  Languages,
  LayoutGrid,
  LogIn,
  Mail,
  MessageCircle,
  MessageSquareText,
  Phone,
  Presentation,
  Receipt,
  ShieldCheck,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

/**
 * The header's menus as plain data, so the server builds them (in the visitor's
 * language, with only the contact links that are set) and the desktop menu and
 * the mobile drawer render the same entries. Icons travel as names: a component
 * cannot cross from a server component into a client one.
 */
export const NAV_ICONS = {
  overview: LayoutGrid,
  tour: CirclePlay,
  ai: Sparkles,
  why: BadgeCheck,
  security: ShieldCheck,
  roles: Users,
  "whatsapp-diary": MessageCircle,
  "whatsapp-attendance": MessageSquareText,
  "fee-management": Receipt,
  "test-paper-generator": FileText,
  attendance: CalendarCheck,
  "multi-campus": Building2,
  urdu: Languages,
  faq: CircleHelp,
  billing: CreditCard,
  demo: Presentation,
  email: Mail,
  phone: Phone,
  signIn: LogIn,
} satisfies Record<string, LucideIcon>;

export type NavIconName = keyof typeof NAV_ICONS;

export type NavLink = {
  href: string;
  label: string;
  body?: string;
  icon: NavIconName;
  /** A WhatsApp, mailto or tel link: a plain anchor, not the router. */
  external?: boolean;
};

export type NavGroup = { title: string; links: NavLink[] };

export type NavMenu = {
  id: string;
  label: string;
  /** The panel's width on wide screens. */
  width: "sm" | "lg";
  groups: NavGroup[];
  /** A card beside the groups: the one thing to do next. */
  feature?: { title: string; body: string; href: string; cta: string };
  /** A line under the groups, with a link. */
  footer?: { text: string; href: string; label: string };
};

export type NavEntry = { kind: "menu"; menu: NavMenu } | { kind: "link"; id: string; href: string; label: string };
