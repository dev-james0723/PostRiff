export type NativeFormat = {id: string; label: string};
export type Channel = {id: string; name: string; group: string; formats: NativeFormat[]; defaultLanguage: string; connection: 'not_connected'|'connected_identity'; publishReady: boolean};
export type Template = {id: string; version: number; name: string; kind: 'article'|'caption'|'visual'|'motion'; body: string; origin: 'default'|'personal'; hash: string};
export type Asset = {id: string; name: string; mime: string; size: number; sha256: string; alt: string; createdAt: string; url: string};
export type VisualChoice = {id: string; name: string; system: string};
export type DraftInput = {title: string; category: string; source: string; angle: string; channels: string[]; copies: Record<string,string>; languages: Record<string,string>; formats: Record<string,string>; templateId: string; templateVersion: number; visualRef: {theme: string; layouts: string[]}; plannedAt: string; timezone: string; assetIds: string[]};
export type Draft = DraftInput & {id: string; revision: number; createdAt: string; updatedAt: string; archived: boolean; status: 'draft'; planningState: 'planned'|'unplanned'};
export type Activity = {id: string; kind?: string; action?: string; label?: string; message?: string; createdAt?: string; timestamp?: string; [key: string]: unknown};
export type Bootstrap = {workspace: {name: string; phase: string; storage: string; version: string}; channels: Channel[]; templates: Template[]; visualCatalog: {themes: VisualChoice[]; layouts: VisualChoice[]}; drafts: Draft[]; assets: Asset[]; activity: Activity[]; capabilities: {publishing: boolean; scheduling: boolean; agentBridge: boolean}};

export const emptyDraft = (): DraftInput => ({title:'',category:'',source:'',angle:'',channels:[],copies:{},languages:{},formats:{},templateId:'',templateVersion:0,visualRef:{theme:'',layouts:[]},plannedAt:'',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',assetIds:[]});
export function draftInput(draft: Draft): DraftInput {
  return Object.fromEntries(Object.keys(emptyDraft()).map(key => [key, draft[key as keyof DraftInput]])) as DraftInput;
}
