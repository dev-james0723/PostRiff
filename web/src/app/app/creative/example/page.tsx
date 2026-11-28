import type { Metadata } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Surface } from '@/components/rafii/surface';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SampleCutPlayer } from './sample-cut-player';

export const metadata: Metadata = { title: 'Compare a sample edit' };

const secondShotDescription = 'A close-up of the dial on dark green, with the orange hand pointing up and left.';
const moments = [
  {
    time: '500ms', label: 'Opening · 0.5 s',
    original: 'A large dial on cream, with the orange hand pointing left.',
    revised: 'A smaller dial on dark green, with the orange hand tilted slightly upward.'
  },
  {
    time: '2000ms', label: 'Second shot · 2 s',
    original: secondShotDescription, revised: secondShotDescription
  }
];

export default function SampleEditPage() {
  return (
    <PageContainer pageTitle='Compare a sample edit' density='creative'
      pageDescription='Play the four-second timer study to see how changing one shot affects the finished video.'
      pageHeaderAction={<Link href='/app/creative' className='text-sm underline underline-offset-4'>Back to Video Studio</Link>}>
      <SampleCutPlayer />
      <Surface as='section' material='quiet' className='grid gap-3' aria-labelledby='hypit-in-rafii'>
        <h2 id='hypit-in-rafii' className='text-lg font-medium'>How Rafii uses the Hypit workflow</h2>
        <p>Hypit starts with a brief or a reference video. Its Studio brings footage, speech, captions, graphics and sound
          onto one timeline. You can time a graphic to a spoken word and reuse the takes you like as you revise.</p>
        <p>Rafii uses the cutting rhythm of a reference and your brand brief to plan new shots. In Rafii’s own Video Studio
          you can trim or replace footage, reorder shots, edit each shot’s caption and export the result as an MP4.</p>
        <p className='text-muted-foreground text-sm'>Rafii’s editor currently works shot by shot. Separate audio and graphics
          tracks, word-by-word caption timing and comments pinned to a moment are still missing.</p>
      </Surface>
      <Surface as='section' material='paper' className='grid gap-2' aria-labelledby='edit-result'>
        <h2 id='edit-result' className='text-lg font-medium'>What changed in the export?</h2>
        <p>Comparing both MP4s frame by frame, all 30 frames of the opening changed. The remaining 66 frames matched exactly.</p>
        <Tabs defaultValue={moments[0].time} className='my-2'>
          <TabsList aria-label='Comparison time'>
            {moments.map(({ time, label }) => <TabsTrigger key={time} value={time}>{label}</TabsTrigger>)}
          </TabsList>
          {moments.map(({ time, original, revised }) => (
            <TabsContent key={time} value={time} keepMounted>
              <div className='grid max-w-md grid-cols-2 gap-3'>
                {[
                  { file: 'original-cut', label: 'First cut', description: original },
                  { file: 'revised-cut', label: 'Revised opening', description: revised }
                ].map(({ file, label, description }) => (
                  <figure key={file}>
                    <figcaption className='mb-1 font-medium'>{label}</figcaption>
                    <Image src={`/rafii/studio-examples/${file}-${time}.png`} alt={description}
                      width={360} height={640} unoptimized className='h-auto w-full rounded-lg' />
                  </figure>
                ))}
              </div>
            </TabsContent>
          ))}
        </Tabs>
        <p className='text-muted-foreground text-sm'>These clips use original animations and synthesized tones. The study demonstrates cut detection, scene editing and MP4 export. Automatic video cloning, word-level timing and batch variants are outside this demonstration.</p>
      </Surface>
      <Surface as='section' material='quiet' className='grid gap-2' aria-labelledby='timing-study'>
        <h2 id='timing-study' className='text-lg font-medium'>From a longer reference to a motion storyboard</h2>
        <p>Rafii found 10 timing intervals in an 89-second excerpt of Hypit’s explainer and planned 17 shots for a new brief.
          The local storyboard renderer illustrates those timings with original animated cards.</p>
        <div className='flex flex-wrap gap-4 text-sm'>
          <Link prefetch={false} href='/rafii/studio-examples/hypit-timing-study.mp4' className='underline underline-offset-4'>Play the motion storyboard</Link>
          <a href='https://github.com/hypit-ai/hypit/tree/e4abc8b246e72600fc186d881fa831074e1060f5/examples/complex-explainer' className='underline underline-offset-4'>Hypit reference example</a>
        </div>
      </Surface>
    </PageContainer>
  );
}
