import type { CreativeProject, CreativeScene } from '../../lib/api/creative-video';
import type { AgentTurnRequest } from '../../lib/agent-runtime/types';

export type PhotoFormat = 'thumbnail' | 'product';

export function campaignPhotoBrief(format: PhotoFormat, project: CreativeProject, scene: CreativeScene) {
  const index = project.scenes.findIndex(s => s.sceneId === scene.sceneId) + 1;
  const instruction = format === 'thumbnail'
    ? 'Make an original video thumbnail with a clear focal point that reads at a small size.'
    : 'Make an original product photo. Preserve the visible details of any product photo I attach.';
  const start = scene.sourceStartMs;
  const segment = start === undefined ? undefined : project.analysis?.scenes.find(s => s.startMs <= start && start < s.endMs);
  const light = segment?.measurements?.meanLuma;
  const lighting = typeof light === 'number'
    ? `Use a ${light < 0.3 ? 'low-key' : light > 0.7 ? 'bright' : 'mid-toned'} setting for this shot.`
    : '';
  // Saved shot directions can contain routing-scoped learned preferences. Only carry the
  // user-supplied campaign and editorial facts into this independently reviewed request.
  return [instruction, `Campaign: ${project.title}. Revision ${project.revision}, shot ${index} (${scene.purpose}).`,
    `Format: ${project.platform}, ${project.aspectRatio}.`, lighting, project.brief].filter(Boolean).join('\n').slice(0, 1000).trim();
}

export async function photoTurnRequest(scope: string[], text: string, photoId: string): Promise<AgentTurnRequest> {
  const args = text.trim();
  if (!args || args.length > 1000) throw new Error('Enter an image brief of up to 1,000 characters.');
  const bytes = new TextEncoder().encode(JSON.stringify([...scope, args, photoId]));
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  const key = Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
  return {
    message: '/image ' + args, command: { name: 'image', args }, modality: 'text',
    idempotencyKey: 'campaign-photo-' + key,
    ...(photoId ? { attachments: [{ assetId: photoId, role: 'reference' as const }] } : {})
  };
}
