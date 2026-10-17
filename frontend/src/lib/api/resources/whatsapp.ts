import { api } from "@/lib/api/client";
import type {
  CustomMessageRequest,
  DiaryAgentSettingsRead,
  DiaryAgentSettingsWrite,
  DiaryDraftRead,
  DiaryPreviewRead,
  FeeNoticePreview,
  FeeNoticeQueueRequest,
  Page,
  PageParams,
  QueueResult,
  WhatsAppConnectionRead,
  WhatsAppGroupRead,
  WhatsAppGroupWrite,
  WhatsAppMessageRead,
  WhatsAppMessageStatus,
  WhatsAppQrRead,
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

  /** The campus's linked number on the WAHA gateway. `configured=false` = other backend. */
  connection: () => api.get<WhatsAppConnectionRead>("/whatsapp/connection"),
  /** Starts (or restarts) the campus session; it then moves to SCAN_QR_CODE. */
  connect: () => api.post<WhatsAppConnectionRead>("/whatsapp/connection"),
  /** 409 `NO_QR_CODE` unless the session is waiting for a scan. */
  qr: () => api.get<WhatsAppQrRead>("/whatsapp/connection/qr"),
  disconnect: () => api.delete<void>("/whatsapp/connection"),
};

/**
 * Mirrors backend/app/modules/diary_agent. Teachers never call these — they post the
 * diary by sending a photo to the school's number; the office configures the format.
 */
export const diaryAgentApi = {
  settings: () => api.get<DiaryAgentSettingsRead>("/diary-agent/settings"),
  saveSettings: (body: DiaryAgentSettingsWrite) =>
    api.put<DiaryAgentSettingsRead>("/diary-agent/settings", body),
  /** A sample diary rendered in the given (unsaved) format. */
  preview: (body: DiaryAgentSettingsWrite) =>
    api.post<DiaryPreviewRead>("/diary-agent/preview", body),
  drafts: (params: PageParams = {}) =>
    api.get<Page<DiaryDraftRead>>("/diary-agent/drafts", { params: { ...params } }),
};
