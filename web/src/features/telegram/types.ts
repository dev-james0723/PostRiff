export interface TelegramCapability {
  state: string; enabled: boolean; implemented: boolean; e2eTested: boolean; candidateExecution?: boolean;
  api: string; connectionType: string; missingRights: string[]; limitation: string;
}
export interface TelegramDestination {
  connectionId: string; connectionType: string; chatId: string; title: string; username?: string;
  destinationType: string; membership: string; administrator: boolean;
  administratorRights: Record<string, boolean>; chatPermissions: Record<string, boolean>;
  linkedDiscussionChatId?: string; businessConnectionId?: string;
  businessState?: { isEnabled: boolean; rights: Record<string, boolean> };
  messageThreadId?: number; directMessagesTopicId?: number; lastVerifiedAt: number;
  availableCapabilities: number; totalCapabilities: number; capabilities: Record<string, TelegramCapability>;
  schedulingMode: 'rafii'; readiness: string;
}
export interface TelegramInbox {
  messages: { message: TelegramMessage; deleted: boolean; rafiiJobId?: string }[];
  topics: { id: string; kind: string; title?: string; closed: boolean }[];
  coverage: string; ordinaryDeletionDetection: string;
}
export interface TelegramMessage {
  message_id: number; date: number; text?: string; caption?: string; message_thread_id?: number;
  reply_to_message?: { message_id: number }; direct_messages_topic?: { topic_id: number };
  poll?: { question: string; options: { text: string; voter_count: number }[]; is_closed: boolean };
  suggested_post_info?: { price?: { amount: number } }; [key: string]: unknown;
}
export interface TelegramFile { recordId: string; fileId: string; kind: string; descriptor: { file_name?: string; title?: string } }
export interface TelegramOperation { operationId: string; digest: string; preview: Record<string, unknown>; expiresAt?: number }

export type TelegramControls = { paused: boolean; approvalPolicy: 'always' | 'scoped_auto'; allowedConnections: string[]; allowedActions: string[]; retentionDays: number; revision: number };
export type TelegramBotAccess = { restricted: boolean; addedUserIds: number[] };
export type TelegramBotAccessPreview = { preview: { botId: string; username: string; before: TelegramBotAccess; after: TelegramBotAccess; ownerAlwaysHasAccess: boolean }; proof: string; keyId: string };
