"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import {
  diaryAgentApi,
  whatsappApi,
  type WhatsAppMessageListParams,
} from "@/lib/api/resources/whatsapp";
import type {
  CustomMessageRequest,
  DiaryAgentSettingsWrite,
  FeeNoticeQueueRequest,
  PageParams,
  QueueResult,
  WhatsAppGroupWrite,
  WhatsAppSettingsWrite,
} from "@/lib/api/types";

export function useWhatsAppGroups() {
  return useQuery({ queryKey: queryKeys.whatsapp.groups, queryFn: () => whatsappApi.groups() });
}

export function useWhatsAppSettings() {
  return useQuery({
    queryKey: queryKeys.whatsapp.settings,
    queryFn: () => whatsappApi.settings(),
  });
}

export function useFeeNoticePreview(period: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.whatsapp.preview(period),
    queryFn: () => whatsappApi.previewFeeNotices(period),
    enabled,
  });
}

export function useWhatsAppMessages(params: WhatsAppMessageListParams) {
  return useQuery({
    queryKey: queryKeys.whatsapp.messages(params),
    queryFn: () => whatsappApi.messages(params),
    placeholderData: (previous) => previous,
  });
}

function useInvalidateWhatsApp() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: queryKeys.whatsapp.all });
}

export function useSaveWhatsAppGroup() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: WhatsAppGroupWrite }) =>
      id ? whatsappApi.updateGroup(id, body) : whatsappApi.createGroup(body),
    onSuccess: (group, { id }) => {
      void invalidate();
      toast.success(id ? "Group updated" : "Group linked", group.name);
    },
    onError: (error) => toast.error("Couldn't save the group", errorMessage(error)),
  });
}

export function useDeleteWhatsAppGroup() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (id: string) => whatsappApi.deleteGroup(id),
    onSuccess: () => {
      void invalidate();
      toast.success("Group unlinked");
    },
    onError: (error) => toast.error("Couldn't unlink the group", errorMessage(error)),
  });
}

export function useSaveWhatsAppSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: WhatsAppSettingsWrite) => whatsappApi.saveSettings(body),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.whatsapp.settings, settings);
      void queryClient.invalidateQueries({ queryKey: ["whatsapp", "preview"] });
      toast.success("WhatsApp settings saved");
    },
    onError: (error) => toast.error("Couldn't save the settings", errorMessage(error)),
  });
}

function queuedToast(result: QueueResult) {
  const skipped = result.skipped ?? [];
  if (result.queued === 0) {
    toast.error("Nothing was queued", skipped[0]?.reason ?? undefined);
    return;
  }
  toast.success(
    `${result.queued} message${result.queued === 1 ? "" : "s"} queued`,
    skipped.length ? `${skipped.length} group(s) skipped.` : undefined,
  );
}

export function useQueueFeeNotices() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (body: FeeNoticeQueueRequest) => whatsappApi.queueFeeNotices(body),
    onSuccess: (result) => {
      void invalidate();
      queuedToast(result);
    },
    onError: (error) => toast.error("Couldn't queue the fee notice", errorMessage(error)),
  });
}

export function useSendCustomMessage() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (body: CustomMessageRequest) => whatsappApi.sendCustom(body),
    onSuccess: (result) => {
      void invalidate();
      queuedToast(result);
    },
    onError: (error) => toast.error("Couldn't queue the message", errorMessage(error)),
  });
}

export function useRetryWhatsAppMessage() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (id: string) => whatsappApi.retry(id),
    onSuccess: () => {
      void invalidate();
      toast.success("Message queued again");
    },
    onError: (error) => toast.error("Couldn't retry", errorMessage(error)),
  });
}

export function useCancelWhatsAppMessage() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: (id: string) => whatsappApi.cancel(id),
    onSuccess: () => {
      void invalidate();
      toast.success("Message cancelled");
    },
    onError: (error) => toast.error("Couldn't cancel", errorMessage(error)),
  });
}

// ---------------------------------------------------------------------------
// The school's WhatsApp number (WAHA gateway session)
// ---------------------------------------------------------------------------

/** Session states that settle by themselves — poll until they do. */
const TRANSIENT_STATUSES = new Set(["STARTING", "SCAN_QR_CODE"]);

export function useWhatsAppConnection() {
  return useQuery({
    queryKey: queryKeys.whatsapp.connection,
    queryFn: () => whatsappApi.connection(),
    refetchInterval: (query) =>
      TRANSIENT_STATUSES.has(query.state.data?.status ?? "") ? 3_000 : false,
  });
}

/** The pairing QR. WhatsApp rotates it every ~20s, so it is refetched on that cadence. */
export function useWhatsAppQr(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.whatsapp.qr,
    queryFn: () => whatsappApi.qr(),
    enabled,
    refetchInterval: enabled ? 20_000 : false,
    // A 409 NO_QR_CODE just means the session moved on; the status poll catches up.
    retry: false,
    gcTime: 0,
  });
}

export function useConnectWhatsApp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => whatsappApi.connect(),
    onSuccess: (connection) => {
      queryClient.setQueryData(queryKeys.whatsapp.connection, connection);
      toast.success("Starting WhatsApp", "The QR code appears in a few seconds.");
    },
    onError: (error) => toast.error("Couldn't start WhatsApp", errorMessage(error)),
  });
}

export function useDisconnectWhatsApp() {
  const invalidate = useInvalidateWhatsApp();
  return useMutation({
    mutationFn: () => whatsappApi.disconnect(),
    onSuccess: () => {
      void invalidate();
      toast.success("WhatsApp disconnected");
    },
    onError: (error) => toast.error("Couldn't disconnect", errorMessage(error)),
  });
}

// ---------------------------------------------------------------------------
// Diary agent
// ---------------------------------------------------------------------------

export function useDiaryAgentSettings() {
  return useQuery({
    queryKey: queryKeys.whatsapp.diarySettings,
    queryFn: () => diaryAgentApi.settings(),
  });
}

/** A sample diary in the (unsaved) format. Pass debounced values — this hits the server. */
export function useDiaryAgentPreview(body: DiaryAgentSettingsWrite, enabled = true) {
  return useQuery({
    queryKey: queryKeys.whatsapp.diaryPreview(body),
    queryFn: () => diaryAgentApi.preview(body),
    enabled: enabled && body.template.trim() !== "",
    placeholderData: (previous) => previous,
    retry: false,
  });
}

export function useDiaryDrafts(params: PageParams) {
  return useQuery({
    queryKey: queryKeys.whatsapp.diaryDrafts(params),
    queryFn: () => diaryAgentApi.drafts(params),
    placeholderData: (previous) => previous,
  });
}

export function useSaveDiaryAgentSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DiaryAgentSettingsWrite) => diaryAgentApi.saveSettings(body),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.whatsapp.diarySettings, settings);
      toast.success("Diary format saved");
    },
    onError: (error) => toast.error("Couldn't save the diary format", errorMessage(error)),
  });
}
