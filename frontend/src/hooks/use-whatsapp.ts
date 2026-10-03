"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { whatsappApi, type WhatsAppMessageListParams } from "@/lib/api/resources/whatsapp";
import type {
  CustomMessageRequest,
  FeeNoticeQueueRequest,
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
      toast.success("Fee notice settings saved");
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
