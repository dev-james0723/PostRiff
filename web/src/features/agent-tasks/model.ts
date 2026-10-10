import type { TaskReceipt, TaskState } from '@/lib/agent-runtime/tasks';
export type Language = 'en' | 'zh-Hant' | 'zh-Hans';
const COPY = {
  title: ['Tasks', '任務', '任务'], subtitle: ['Follow your work, review approvals and inspect results.', '查看工作進度、審批及執行結果。', '查看工作进度、审批及执行结果。'],
  open: ['In progress', '進行中', '进行中'], needs_me: ['Needs you', '待你處理', '待你处理'], recent: ['Recent', '最近', '最近'],
  mine: ['My tasks', '我的任務', '我的任务'], workspace: ['Workspace tasks', '工作區任務', '工作区任务'],
  queued: ['Queued', '等候執行', '等候执行'], running: ['Running', '執行中', '执行中'], awaiting_approval: ['Awaiting approval', '等候批核', '等候批准'],
  blocked: ['Blocked', '需要處理', '需要处理'], completed: ['Completed', '已完成', '已完成'], failed: ['Failed', '未成功', '未成功'], cancelled: ['Cancelled', '已取消', '已取消'],
  loading: ['Loading tasks…', '正在載入任務…', '正在加载任务…'], unavailable: ['Tasks are unavailable in this workspace.', '此工作區暫未開放任務中心。', '此工作区暂未开放任务中心。'],
  empty: ['No tasks in this view.', '這個列表暫時沒有任務。', '这个列表暂时没有任务。'], select: ['Select a task to see its progress and evidence.', '選擇任務以查看進度及執行記錄。', '选择任务以查看进度及执行记录。'],
  reload: ['Refresh', '重新整理', '刷新'], more: ['Load more', '載入更多', '加载更多'], conversation: ['Open conversation', '開啟對話', '打开对话'],
  steps: ['Steps', '步驟', '步骤'], approvals: ['Review approvals', '待批核事項', '待批准事项'], evidence: ['Execution evidence', '執行證據', '执行证据'],
  history: ['Execution history', '執行紀錄', '执行记录'], noHistory: ['No recorded events yet.', '暫時沒有執行紀錄。', '暂时没有执行记录。'],
  changed: ['This action changed. Go back and review the current version.', '此操作已變更，請返回核對最新版本。', '此操作已更改，请返回核对最新版本。'],
  uncertain: ['The result is not confirmed. Retry this same request to reconcile it before starting another action.', '尚未確認執行結果，請重試同一要求以核對記錄，再開始其他操作。', '尚未确认执行结果，请重试同一请求以核对记录，再开始其他操作。'],
  verified: ['Verified', '已核實', '已核实'], unverified: ['Not verified', '尚未核實', '尚未核实'], partial: ['Some steps completed. The whole task is not complete.', '部分步驟已完成，整項任務尚未完成。', '部分步骤已完成，整项任务尚未完成。'],
  cancel: ['Cancel task', '取消任務', '取消任务'], continue: ['Continue task', '繼續任務', '继续任务'], retry: ['Retry step', '重試步驟', '重试步骤'], undo: ['Undo change', '還原變更', '还原更改'],
  approve: ['Approve this action', '批准此操作', '批准此操作'], reject: ['Reject', '拒絕', '拒绝'], confirm: ['Confirm', '確認', '确认'], back: ['Go back', '返回', '返回'],
  submitted: ['Request received. Checking the server record…', '已收到要求，正在核對伺服器記錄…', '已收到请求，正在核对服务器记录…'],
  cancelNote: ['Rafii stops after the current step. An accepted external action may still finish.', 'Rafii 會在目前步驟結束後停止。已接收的外部操作仍可能完成。', 'Rafii 会在当前步骤结束后停止。已接收的外部操作仍可能完成。'],
  continueNote: ['Continue the saved task using its current permissions and budget. AI work may use credits.', '按目前權限及預算繼續已儲存的任務。AI 工作可能使用額度。', '按当前权限及预算继续已保存的任务。AI 工作可能使用额度。'],
  undoNote: ['Restore this change only if the resource is unchanged and Undo is still available.', '只有資源未被再次修改且仍可還原時，才會還原此變更。', '只有资源未被再次修改且仍可还原时，才会还原此更改。'],
  reviewNote: ['Review the exact action below before approving.', '批准前請核對以下操作內容。', '批准前请核对以下操作内容。'],
  expired: ['This approval has expired. Refresh to see the current state.', '此批核已過期，請重新整理以查看最新狀態。', '此批准已过期，请刷新以查看最新状态。'],
  stepUp: ['Complete the additional verification on the original action page.', '請在原操作頁面完成額外驗證。', '请在原操作页面完成额外验证。'],
  result: ['View result', '查看結果', '查看结果'], completedSteps: ['steps completed', '個步驟已完成', '个步骤已完成'],
  noEvidence: ['No verified execution receipt is available yet.', '暫時沒有已核實的執行收據。', '暂时没有已核实的执行收据。'],
  unknownCost: ['Some cost is not yet known.', '部分費用仍未確定。', '部分费用仍未确定。'],
  access: ['Only details you are allowed to see are shown.', '只顯示你有權查看的詳情。', '只显示你有权查看的详情。']
  , incomplete: ['The complete action cannot be shown here. Open the original conversation to review it.', '這裡未能顯示完整操作，請開啟原對話核對。', '这里未能显示完整操作，请打开原对话核对。']
} as const;
export type CopyKey = keyof typeof COPY;
export function language(locale: string): Language { return /^zh/i.test(locale) ? /Hans|CN|SG/i.test(locale) ? 'zh-Hans' : 'zh-Hant' : 'en'; }
export function text(key: CopyKey, lang: Language) { return COPY[key][lang === 'en' ? 0 : lang === 'zh-Hant' ? 1 : 2]; }
export function stateLabel(state: TaskState, lang: Language) { return Object.hasOwn(COPY, state) ? text(state as CopyKey, lang) : state; }
export function isOpen(state?: string) { return ['queued', 'running', 'awaiting_approval', 'blocked'].includes(state ?? ''); }
export function safeTaskHref(value?: string | null): string | null {
  if (typeof value !== 'string' || !value.startsWith('/app') || /[\\\s]|%(?:2f|5c)/i.test(value)) return null;
  try {
    const parsed = new URL(value, 'https://rafii.invalid');
    return parsed.origin === 'https://rafii.invalid' && (parsed.pathname === '/app' || parsed.pathname.startsWith('/app/')) ? value : null;
  } catch { return null; }
}
export function receiptVerified(receipt: TaskReceipt): boolean {
  if (receipt.verified !== true || receipt.outcome !== 'applied' || receipt.checks.some((check) => check.ok !== true)) return false;
  return !receipt.providerReceipt || (receipt.providerReceipt.state === 'verified' && Boolean(receipt.providerReceipt.verifiedAt));
}
export function changedResourceHref(ref: { type: string; id: string }): string | null {
  if (!/^[A-Za-z0-9_.:-]{1,120}$/.test(ref.id)) return null;
  if (ref.type === 'draft') return `/app/queue?view=drafts&draft=${encodeURIComponent(ref.id)}`;
  if (ref.type === 'source') return `/app/ideas?source=${encodeURIComponent(ref.id)}`;
  // Library has no asset-query deep link. Its native history exposes the exact changed assets.
  if (['library_asset', 'library_collection', 'asset'].includes(ref.type)) return '/app/library';
  return null;
}
export function summaryLines(value: Record<string, unknown>): { lines: { label: string; value: string }[]; complete: boolean } {
  const out: { label: string; value: string }[] = [];
  let complete = true;
  function visit(row: Record<string, unknown>, prefix: string, depth: number) {
    if (depth > 8 || out.length > 200) { complete = false; return; }
    for (const [key, item] of Object.entries(row)) {
      const label = `${prefix}${key.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')}`;
      if (item === null || ['string', 'number', 'boolean'].includes(typeof item)) {
        const content = String(item);
        if (content.length > 50000 || out.length >= 200) { complete = false; continue; }
        out.push({ label, value: content });
      } else if (item && typeof item === 'object') {
        if (Object.keys(item).length) visit(item as Record<string, unknown>, `${label} · `, depth + 1);
        else out.push({ label, value: Array.isArray(item) ? '[]' : '{}' });
      } else complete = false;
    }
  }
  visit(value, '', 0); return { lines: out, complete: complete && out.length > 0 };
}
