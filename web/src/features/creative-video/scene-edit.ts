import type { CreativeScene, CreativeSceneEdit, RenderedCaption } from '@/lib/api/creative-video';

export interface SceneDraft {
  direction: string;
  caption: string;
  seconds: string;
  startSeconds: string;
  clipId: string;
  clipRightsConfirmed: boolean;
}

export function draftScene(scene: CreativeScene): SceneDraft {
  return {
    direction: scene.direction, caption: scene.caption, seconds: String(scene.durationMs / 1000),
    startSeconds: String((scene.trimStartMs ?? 0) / 1000), clipId: scene.clipId ?? '', clipRightsConfirmed: false
  };
}

type Drafts = Record<string, SceneDraft>;

export function changedScenes(scenes: CreativeScene[], drafts: Drafts): CreativeSceneEdit[] {
  const changes: CreativeSceneEdit[] = [];
  for (const scene of scenes) {
    const draft = drafts[scene.sceneId];
    if (!draft) continue;
    const durationMs = Math.round(Number(draft.seconds) * 1000);
    const changedClip = (scene.clipId ?? '') !== draft.clipId;
    const trimStartMs = Math.round(Number(draft.startSeconds) * 1000);
    const changedTrim = trimStartMs !== (changedClip ? 0 : scene.trimStartMs ?? 0);
    if (draft.direction === scene.direction && draft.caption === scene.caption && durationMs === scene.durationMs && !changedClip && !changedTrim) continue;
    const patch: CreativeSceneEdit = { sceneId: scene.sceneId, direction: draft.direction, caption: draft.caption, durationMs };
    if (changedTrim) patch.trimStartMs = trimStartMs;
    if (changedClip) {
      patch.clipId = draft.clipId || null;
      if (draft.clipId && draft.clipRightsConfirmed) patch.clipRightsConfirmed = true;
    }
    changes.push(patch);
  }
  return changes;
}

export function editIssue(scenes: CreativeScene[], drafts: Drafts, referenceId: string | null): string | null {
  let total = 0;
  for (const [index, scene] of scenes.entries()) {
    const draft = drafts[scene.sceneId] ?? draftScene(scene);
    const prefix = `Scene ${index + 1}`;
    if (!draft.direction.trim() || draft.direction.length > 600) return `${prefix} needs a direction of up to 600 characters.`;
    if (draft.caption.length > 120) return `${prefix} needs a caption of up to 120 characters.`;
    const durationMs = Math.round(Number(draft.seconds) * 1000);
    if (!/^\d+(\.\d{1,3})?$/.test(draft.seconds) || durationMs < 42 || durationMs > 8000)
      return `${prefix} needs a duration between 0.042 and 8 seconds, to the nearest millisecond.`;
    if (!/^\d+(\.\d{1,3})?$/.test(draft.startSeconds) || Number(draft.startSeconds) >= 90)
      return `${prefix} needs a source start from 0 to 89.999 seconds.`;
    if (!draft.clipId && Number(draft.startSeconds) !== 0) return `Choose footage before trimming ${prefix.toLowerCase()}.`;
    if (draft.clipId && draft.clipId === referenceId) return `${prefix} needs original footage distinct from the reference.`;
    if (draft.clipId && draft.clipId !== scene.clipId && !draft.clipRightsConfirmed)
      return `Confirm the rights to the new footage for scene ${index + 1}.`;
    total += durationMs;
  }
  return total > 90000 ? 'Keep the complete video within 90 seconds.' : null;
}

export function formatUsd(micro: number): string {
  return (micro / 1_000_000).toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

export function unresolved(scene: CreativeScene): boolean {
  const state = scene.generation?.state;
  return state === 'pending' || state === 'submitting' || state === 'unknown' || state === 'cancelling';
}

function timestamp(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(n => String(n).padStart(2, '0')).join(':') + '.' + String(ms % 1000).padStart(3, '0');
}

export function captionTrack(scenes?: RenderedCaption[]): string | null {
  const cues = (scenes ?? []).filter(s => s.caption.trim() && Number.isSafeInteger(s.startMs) &&
    Number.isSafeInteger(s.endMs) && s.startMs >= 0 && s.endMs > s.startMs);
  if (!cues.length) return null;
  return 'WEBVTT\n\n' + cues.map(s => {
    const text = s.caption.trim().replace(/\s+/g, ' ').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    return `${timestamp(s.startMs)} --> ${timestamp(s.endMs)}\n${text}\n`;
  }).join('\n');
}
