import { api } from "@/lib/api/client";
import type {
  CustomMessageRequest,
  FeeNoticePreview,
  FeeNoticeQueueRequest,
  Page,
  PageParams,
  QueueResult,
  WhatsAppGroupRead,
  WhatsAppGroupWrite,
  WhatsAppMessageRead,
  WhatsAppMessageStatus,
  WhatsAppSettingsRead,
  WhatsAppSettingsWrite,
} from "@/lib/api/types";

export type WhatsAppMessageListParams = PageParams & { status?: WhatsAppMessageStatus };

/**
 * Mirrors backend/app/modules/whatsapp/router.py. Everything here QUEUES; posting to
 * WhatsApp happens when `app.cli send-whatsapp` drains the outbox.
 */
export const whatsappApi = {
  groups: () => api.get<WhatsAppGroupRead[]>("/whatsapp/groups"),
  createGroup: (body: WhatsAppGroupWrite) => api.post<WhatsAppGroupRead>("/whatsapp/groups", body),
  updateGroup: (id: string, body: WhatsAppGroupWrite) =>
    api.put<WhatsAppGroupRead>(`/whatsapp/groups/${id}`, body),
  deleteGroup: (id: string) => api.delete<void>(`/whatsapp/groups/${id}`),

  settings: () => api.get<WhatsAppSettingsRead>("/whatsapp/settings"),
  saveSettings: (body: WhatsAppSettingsWrite) =>
    api.put<WhatsAppSettingsRead>("/whatsapp/settings", body),

  /** `period` is YYYY-MM; defaults server-side to the current month. */
  previewFeeNotices: (period?: string) =>
    api.get<FeeNoticePreview[]>("/whatsapp/fee-notices/preview", {
      params: period ? { period_label: period } : {},
    }),
  queueFeeNotices: (body: FeeNoticeQueueRequest) =>
    api.post<QueueResult>("/whatsapp/fee-notices", body),

  sendCustom: (body: CustomMessageRequest) => api.post<QueueResult>("/whatsapp/messages", body),
  messages: (params: WhatsAppMessageListParams = {}) =>
    api.get<Page<WhatsAppMessageRead>>("/whatsapp/messages", { params: { ...params } }),
  retry: (id: string) => api.post<void>(`/whatsapp/messages/${id}/retry`),
  cancel: (id: string) => api.delete<void>(`/whatsapp/messages/${id}`),
};
