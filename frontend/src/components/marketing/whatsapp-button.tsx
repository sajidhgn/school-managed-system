import { MessageCircle } from "lucide-react";

import type { MarketingCopy } from "@/components/marketing/copy";
import { whatsappUrl } from "@/lib/site";

/**
 * The floating "Talk on WhatsApp" button on every public page.
 *
 * Shown only when the server has `SITE_WHATSAPP`: the chat opens with a greeting
 * already typed, in the visitor's language.
 */
export function WhatsAppButton({ common }: { common: MarketingCopy["common"] }) {
  const href = whatsappUrl(common.contactMessage);
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="mk-whatsapp">
      <MessageCircle className="size-5 shrink-0" aria-hidden />
      <span className="mk-whatsapp__label">{common.talkOnWhatsApp}</span>
    </a>
  );
}
