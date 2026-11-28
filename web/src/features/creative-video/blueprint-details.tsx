'use client';

import Link from 'next/link';
import { type SyntheticEvent, useState } from 'react';
import { Surface } from '@/components/rafii';
import type { CreativeProject } from '@/lib/api/creative-video';
import { PrivateVideo } from './media';
import { ReferenceContactSheet } from './reference-contact-sheet';

export function BlueprintDetails({ project }: { project: CreativeProject }) {
  const [referenceOpen, setReferenceOpen] = useState(false);
  const { analysis, context } = project;
  const overlays = analysis.overlaySignals;
  const rhythm = analysis.measured?.audioRhythm;
  const speech = analysis.speechTiming;
  const brandFields = [
    ['Brand', context.brand], ['Subject', context.subject], ['Audience', context.audience], ['Campaign purpose', context.purpose], ['Tone', context.tone]
  ].filter(([, value]) => typeof value === 'string' && value.trim());
  return <div className='grid min-w-0 items-start gap-3 lg:grid-cols-2'>
    {project.referenceAssetId && <Surface as='details' material='quiet' padding='md'
      onToggle={(event: SyntheticEvent<HTMLDetailsElement>) => setReferenceOpen(event.currentTarget.open)}>
      <summary className='rafii-focus cursor-pointer rounded-sm text-sm font-medium'>Reference analysis</summary>
      <div className='mt-3 grid gap-3 text-sm'>
        <p>{analysis.width} × {analysis.height} · {analysis.durationMs / 1000} s · {Number(analysis.fps.toFixed(2))} fps · {analysis.hasAudio ? 'Audio present' : 'No audio track'}</p>
        <div><h3 className='font-medium'>Estimated shots</h3>
          {analysis.measured && <p className='text-muted-foreground text-sm'>{analysis.measured.sampledFrameCount} sampled frames, spaced {analysis.measured.sampleIntervalMs} ms apart.</p>}
          <ol className='mt-2 grid gap-1 text-muted-foreground'>
            {analysis.scenes.map((shot, i) => <li key={shot.startMs} className='border-b py-1.5 last:border-0'>
              <span className='flex items-center gap-2 text-foreground'>
                {shot.measurements && <span aria-hidden className='size-3 rounded-sm ring-1 ring-current/20'
                  style={{ backgroundColor: `rgb(${shot.measurements.meanRgb.join(' ')})` }} />}
                Shot {i + 1} · {shot.startMs / 1000}–{shot.endMs / 1000} s
              </span>
              {shot.interpretation && <span className='mt-1 block text-xs'>{shot.interpretation}</span>}
            </li>)}
          </ol>
        </div>
        {referenceOpen && analysis.scenes.length > 0 && <ReferenceContactSheet project={project} />}
        {analysis.measured?.embeddedCaptions && <p>Embedded caption timing · {analysis.measured.embeddedCaptions.state === 'no_embedded_track'
          ? 'No embedded track' : `${analysis.measured.embeddedCaptions.cues.length} cues (${analysis.measured.embeddedCaptions.state.replaceAll('_', ' ')})`}</p>}
        {rhythm && <div>
          <h3 className='font-medium'>Audio rhythm</h3>
          {rhythm.state === 'measured' ? <>
            <p className='text-muted-foreground'>{rhythm.onsetMs.length} detected volume {rhythm.onsetMs.length === 1 ? 'rise' : 'rises'} · {rhythm.resolutionMs} ms sampling windows.</p>
            {rhythm.medianSpacingMs != null && <p>Median interval between rises · {rhythm.medianSpacingMs / 1000} s</p>}
            {rhythm.onsetMs.length > 0 && <details className='mt-1'>
              <summary className='rafii-focus cursor-pointer rounded-sm'>Show timing cues</summary>
              <p className='mt-1 text-muted-foreground'>{rhythm.onsetMs.map(ms => `${ms / 1000} s`).join(' · ')}</p>
            </details>}
          </> : <p className='text-muted-foreground'>{rhythm.state === 'no_audio_track' ? 'The reference has no audio track.' : 'Rhythm measurements are unavailable for this reference.'}</p>}
        </div>}
        {speech && <div>
          <h3 className='font-medium'>Estimated speech timing</h3>
          {speech.state === 'measured' ? <>
            <p className='text-muted-foreground'>Local speech recognition · opening {speech.analyzedDurationMs / 1000} s</p>
            {speech.segments.length ? <ol className='mt-1 grid gap-1'>{speech.segments.map((segment, i) =>
              <li key={i}>Phrase {i + 1} · {segment.startMs / 1000}–{segment.endMs / 1000} s</li>)}</ol> :
              <p>No speech segments were identified in this interval.</p>}
          </> : <p className='text-muted-foreground'>{speech.state === 'no_audio_track' ? 'The reference has no audio track.' : 'The local worker could not estimate speech timing.'}</p>}
        </div>}
        {overlays && <div>
          <h3 className='font-medium'>On-screen text</h3>
          {overlays.state === 'unavailable' ? <p className='text-sm text-muted-foreground'>{overlays.reason === 'english_data_unavailable'
            ? 'English recognition data is unavailable on this worker.' : 'Text recognition was unavailable for this reference.'}</p> : <>
            <p className='text-sm text-muted-foreground'>English text in sampled frames · minimum word confidence {overlays.minimumWordConfidence}/100.</p>
            <ul className='mt-1 grid gap-2'>{overlays.frames.map(frame => <li key={frame.timeMs} className='text-sm'>
              <p>Shot {frame.sceneIndex + 1} at {frame.timeMs / 1000} s · {frame.wordCount > 0
                ? `${frame.wordCount} recognized ${frame.wordCount === 1 ? 'word' : 'words'} · ${frame.meanConfidence}/100 average confidence`
                : 'No words met the confidence threshold'}</p>
              {frame.verticalRegion && <p className='text-muted-foreground'>Typical position in the {frame.verticalRegion} third · median word height {frame.medianWordHeightPct}% of the frame.</p>}
              {frame.interpretiveClues.length > 0 && <p className='text-muted-foreground'>Possible creative device · {frame.interpretiveClues.map(clue =>
                clue === 'question' ? 'question' : 'call to action').join(', ')}.</p>}
            </li>)}</ul>
            {overlays.state === 'partial' && <p className='text-sm text-muted-foreground'>Some sampled frames could not be read.</p>}
          </>}
        </div>}
        {analysis.unavailable?.map(note => <p key={note} className='text-muted-foreground'>{note}</p>)}
        <PrivateVideo key={project.referenceAssetId} assetId={project.referenceAssetId} label='Play reference' />
      </div>
    </Surface>}
    <Surface as='details' material='quiet' padding='md'>
      <summary className='rafii-focus cursor-pointer rounded-sm text-sm font-medium'>Brand and memory used</summary>
      <div className='mt-3 grid gap-3 text-sm'>
        <p>{context.voiceRevision != null ? `Brand voice revision ${context.voiceRevision}` : 'No saved voice revision supplied.'}</p>
        {brandFields.length > 0 && <dl className='grid gap-2'>
          {brandFields.map(([label, value]) => <div key={label}><dt className='text-muted-foreground text-xs'>{label}</dt><dd>{value}</dd></div>)}
        </dl>}
        <div><h3 className='font-medium'>Reusable preferences{context.styleRevision != null ? ` · Revision ${context.styleRevision}` : ''}</h3>
          {context.preferences.length
            ? <ul className='mt-1 list-disc space-y-1 pl-5'>{context.preferences.map((item, i) => <li key={i}>{item}</li>)}</ul>
            : <p className='text-muted-foreground mt-1'>No approved preferences were included in this blueprint.</p>}
        </div>
        <p className='text-muted-foreground'>Cloud generation {context.cloudAllowed ? 'permitted by the workspace privacy setting.' : 'disabled by the workspace privacy setting.'}</p>
        <div className='flex flex-wrap gap-4'>
          <Link href='/app/workspace/brand' className='rafii-focus rounded-sm underline underline-offset-4'>Brand Brain</Link>
          <Link href='/app/workspace/memory' className='rafii-focus rounded-sm underline underline-offset-4'>Creative Memory</Link>
        </div>
      </div>
    </Surface>
  </div>;
}
