'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useSignInAgain } from '@/lib/auth/use-sign-in-again';
import type { Recipe, RecipeList, RecipeReport, RecipeSettings } from './types';

const field = 'min-h-10 w-full rounded-md border bg-background px-3 py-2 text-sm';
const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const date = (value: number) => new Date(value * 1000).toLocaleString();

export function WorkflowRecipesPanel() {
  const { workspaceId } = useWorkspaceApi();
  return <RecipesPanel key={workspaceId} />;
}

function RecipesPanel() {
  const { api, workspaceId: w } = useWorkspaceApi();
  const client = useQueryClient();
  const signInAgain = useSignInAgain();
  const query = useQuery({ queryKey: ['workflow-recipes', w], queryFn: () => api.workflowRecipes(w), enabled: Boolean(w), retry: false });
  const [editing, setEditing] = useState<{ recipe?: Recipe; settings: RecipeSettings } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [freshSignIn, setFreshSignIn] = useState(false);
  const [reviewed, setReviewed] = useState<string | null>(null);
  const [report, setReport] = useState<RecipeReport | null>(null);
  const keys = useRef(new Map<string, string>());
  const data = query.data;
  async function act(name: string, fn: (key: string) => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError(null); setFreshSignIn(false);
    const requestKey = keys.current.get(name) ?? crypto.randomUUID();
    keys.current.set(name, requestKey);
    try {
      await fn(requestKey);
      keys.current.delete(name);
      await client.invalidateQueries({ queryKey: ['workflow-recipes', w] });
      setReviewed(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not finish this request.');
      setFreshSignIn(failure instanceof ApiError && failure.code === 'step_up_required');
    } finally { setBusy(false); }
  }
  if (query.error instanceof ApiError && [404, 503].includes(query.error.status)) return null;
  if (!data) return query.error ? <p role='alert'>Personal recipes are unavailable. <button onClick={() => void query.refetch()} className='underline'>Retry</button></p> : null;
  function create() {
    setEditing({ settings: { templateId: 'library_review', name: 'Review Library metadata', trigger: 'weekly', planningDay: 0, planningHour: 9,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', connectionId: null, collectionId: null,
      expiresAt: Math.floor(Date.now() / 1000) + 28 * 86400, actionsPerDay: 1, actionsTotal: 4, usdMicroPerDay: 0, notificationPolicy: 'failures_and_approvals' } });
  }
  return <section aria-label='Personal workflow recipes' className='mb-8 space-y-4 rounded-xl border p-4 sm:p-6'>
    <div className='flex flex-wrap items-start justify-between gap-3'><div><h2 className='text-lg font-semibold'>Personal workflow recipes</h2><p className='max-w-2xl text-sm text-muted-foreground'>Template-bound Autopilot for stored-data reviews. No model calls, provider sync or publishing. Every run stays visible in Tasks.</p></div><Button variant='outline' disabled={busy} onClick={create}>New recipe</Button></div>
    {!data.explicitPermissions && <p className='text-sm'>Choose explicit <Link className='underline' href='/app/account/agent'>Rafii permissions</Link> before enabling a recipe.</p>}
    {error && <p role='alert' className='text-sm text-destructive'>{error} {freshSignIn && <button className='underline' onClick={() => void signInAgain()}>Sign in again</button>}</p>}
    {editing && <RecipeEditor key={editing.recipe?.id ?? 'new'} value={editing.settings} data={data} busy={busy} onClose={() => setEditing(null)} onSave={(settings) => void act('save:' + (editing.recipe?.id ?? 'new'), async () => { await api.saveWorkflowRecipe(w, settings, editing.recipe?.version ?? null, editing.recipe?.id); setEditing(null); })} />}
    {!data.recipes.length && !editing && <p className='text-sm text-muted-foreground'>Create a recipe, inspect its exact scope and steps, then authorize its limited policy.</p>}
    <div className='grid gap-4 lg:grid-cols-2'>{data.recipes.map(recipe => {
      const template = data.templates.find(item => item.id === recipe.config.templateId);
      return <article key={recipe.id} className='min-w-0 space-y-3 rounded-lg border p-4' aria-label={recipe.config.name}>
        <div className='flex flex-wrap justify-between gap-2'><h3 className='break-words font-medium'>{recipe.config.name}</h3><span className='text-sm'>{recipe.status === 'active' && !recipe.policyCurrent ? 'Policy expired or changed' : recipe.status} · v{recipe.version}</span></div>
        <p className='text-sm text-muted-foreground'>{template?.description}</p>
        <PolicyDetails settings={recipe.config} data={data} />
        <ol className='list-decimal space-y-1 pl-5 text-sm'>{template?.steps.map(step => <li key={step}>{step}</li>)}</ol>
        <p className='text-xs text-muted-foreground'>{template?.preconditions.join('. ')}. {template?.approvalPolicy}</p>
        {recipe.policyId && <details className='text-xs'><summary className='cursor-pointer'>Policy audit</summary><p className='mt-2 break-all'>Policy {recipe.policyId} · recipe v{recipe.version} · template v{template?.version}. {recipe.usedOperations ?? 'Unavailable'} operations reserved.</p></details>}
        {recipe.nextAttemptAt && <p className='text-sm'>After errors, new runs wait until {date(recipe.nextAttemptAt)}. {recipe.consecutiveFailures} consecutive failures.</p>}
        {recipe.status !== 'active' && recipe.status !== 'revoked' && <label className='flex gap-2 text-sm'><input type='checkbox' className='mt-1' checked={reviewed === recipe.id} onChange={e => setReviewed(e.target.checked ? recipe.id : null)} />I reviewed these exact steps, scope, limits, expiry and notification settings.</label>}
        <div className='flex flex-wrap gap-2'>
          {recipe.status !== 'revoked' && <Button size='sm' variant='outline' disabled={busy} onClick={() => setEditing({ recipe, settings: recipe.config })}>Edit settings</Button>}
          {recipe.status !== 'active' && recipe.status !== 'revoked' && <Button size='sm' disabled={busy || !data.explicitPermissions || reviewed !== recipe.id} onClick={() => void act('enable:' + recipe.id + ':' + recipe.version, key => api.enableWorkflowRecipe(w, recipe.id, recipe.version, data.permissionToken, key))}>Enable limited Autopilot</Button>}
          {recipe.status === 'active' && <><Button size='sm' disabled={busy || !recipe.policyCurrent} onClick={() => void act('run:' + recipe.id + ':' + recipe.version, key => api.runWorkflowRecipe(w, recipe.id, recipe.version, key))}>Run now</Button><Button size='sm' variant='outline' disabled={busy} onClick={() => void act('pause:' + recipe.id, () => api.stopWorkflowRecipe(w, recipe.id, recipe.version, 'paused'))}>Pause</Button></>}
          {recipe.status !== 'revoked' && <Button size='sm' variant='outline' disabled={busy} onClick={() => void act('revoke:' + recipe.id, () => api.stopWorkflowRecipe(w, recipe.id, recipe.version, 'revoked'))}>Revoke</Button>}
        </div>
      </article>;
    })}</div>
    {!!data.runs.length && <div className='space-y-2'><div className='flex items-center gap-3'><h3 className='font-medium'>Recent recipe runs</h3><button className='text-sm underline' onClick={() => void query.refetch()}>Refresh</button></div><ul className='space-y-2'>{data.runs.map(run => <li key={run.id} className='flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm'><span>{date(run.createdAt)} · {run.state}</span><Link className='underline' href={'/app/tasks?task=' + run.taskId}>Open task</Link>{run.hasReport && <button className='underline' disabled={busy} onClick={() => void act('report:' + run.id, async () => setReport(await api.workflowRecipeReport(w, run.id)))}>View report</button>}</li>)}</ul></div>}
    {report && <ReportView value={report} close={() => setReport(null)} />}
  </section>;
}

function PolicyDetails({ settings: s, data }: { settings: RecipeSettings; data: RecipeList }) {
  const scope = s.templateId === 'weekly_performance' ? data.connections.find(c => c.id === s.connectionId)?.name ?? 'Selected account unavailable' : s.collectionId ? data.collections.find(c => c.id === s.collectionId)?.name ?? 'Selected collection unavailable' : 'Whole Library';
  return <dl className='grid gap-1 text-sm'><div><dt className='inline font-medium'>Scope: </dt><dd className='inline break-words'>{scope}{s.templateId === 'library_review' ? ' · up to 20 assets' : ' · previous 7 days · first 50 posts'}</dd></div><div><dt className='inline font-medium'>Trigger: </dt><dd className='inline'>{s.trigger === 'weekly' ? `${days[s.planningDay]} at ${String(s.planningHour).padStart(2, '0')}:00 (${s.timeZone})` : 'New document, audio or file uploads after enabling; checked on worker ticks'}</dd></div><div><dt className='inline font-medium'>Limits: </dt><dd className='inline'>{s.actionsPerDay}/day · {s.actionsTotal} total operations · $0 cost · expires {date(s.expiresAt)}</dd></div><div><dt className='inline font-medium'>Errors: </dt><dd className='inline'>At most 3 attempts per run; new runs back off 5, 10, 20 minutes after failures; pause after 3 failed runs.</dd></div><div><dt className='inline font-medium'>Notifications: </dt><dd className='inline'>{s.notificationPolicy === 'none' ? 'None' : s.notificationPolicy === 'all' ? 'All task outcomes, in app' : 'Failures and approval requests, in app'}</dd></div></dl>;
}

function RecipeEditor({ value, data, busy, onSave, onClose }: { value: RecipeSettings; data: RecipeList; busy: boolean; onSave: (settings: RecipeSettings) => void; onClose: () => void }) {
  const [settings, set] = useState(value);
  const template = data.templates.find(t => t.id === settings.templateId)!;
  function change<K extends keyof RecipeSettings>(key: K, value: RecipeSettings[K]) { set(s => ({ ...s, [key]: value })); }
  return <form className='space-y-4 rounded-lg border bg-muted/20 p-4' aria-label='Recipe settings' onSubmit={e => { e.preventDefault(); onSave(Object.fromEntries(['templateId', 'name', 'trigger', 'planningDay', 'planningHour', 'timeZone', 'connectionId', 'collectionId', 'expiresAt', 'actionsPerDay', 'actionsTotal', 'usdMicroPerDay', 'notificationPolicy'].map(key => [key, settings[key as keyof RecipeSettings]])) as RecipeSettings); }}>
    <div className='grid gap-4 sm:grid-cols-2'><label className='space-y-1 text-sm'>Template<select className={field} value={settings.templateId} onChange={e => { const id = e.target.value as RecipeSettings['templateId']; set(s => ({ ...s, templateId: id, name: data.templates.find(t => t.id === id)!.name, trigger: 'weekly', connectionId: id === 'weekly_performance' ? data.connections[0]?.id ?? null : null, collectionId: null })); }}>{data.templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <label className='space-y-1 text-sm'>Name<input className={field} maxLength={80} required value={settings.name} onChange={e => change('name', e.target.value)} /></label>
      {settings.templateId === 'weekly_performance' ? <label className='space-y-1 text-sm'>Connected account<select className={field} required value={settings.connectionId ?? ''} onChange={e => change('connectionId', e.target.value)}><option value=''>Choose an account</option>{data.connections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label> : <label className='space-y-1 text-sm'>Library scope<select className={field} value={settings.collectionId ?? ''} onChange={e => change('collectionId', e.target.value || null)}><option value=''>Whole Library</option>{data.collections.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
      <label className='space-y-1 text-sm'>Trigger<select className={field} value={settings.trigger} onChange={e => change('trigger', e.target.value as RecipeSettings['trigger'])}>{template.triggers.map(t => <option key={t} value={t}>{t === 'weekly' ? 'Weekly' : 'New file uploads'}</option>)}</select></label>
      {settings.trigger === 'weekly' && <><label className='space-y-1 text-sm'>Day<select className={field} value={settings.planningDay} onChange={e => change('planningDay', Number(e.target.value))}>{days.map((day, i) => <option value={i} key={day}>{day}</option>)}</select></label><label className='space-y-1 text-sm'>Hour (0–23)<input className={field} required type='number' min={0} max={23} value={settings.planningHour} onChange={e => change('planningHour', Number(e.target.value))} /></label></>}
      <label className='space-y-1 text-sm'>Time zone<input className={field} required maxLength={64} value={settings.timeZone} onChange={e => change('timeZone', e.target.value)} /></label>
      <label className='space-y-1 text-sm'>Expires (UTC, within 30 days)<input className={field} type='datetime-local' required value={new Date(settings.expiresAt * 1000).toISOString().slice(0, 16)} onChange={e => { if (e.target.value) change('expiresAt', Date.parse(e.target.value + 'Z') / 1000); }} /></label>
      <label className='space-y-1 text-sm'>Operations per day<input className={field} required type='number' min={1} max={5} value={settings.actionsPerDay} onChange={e => change('actionsPerDay', Number(e.target.value))} /></label>
      <label className='space-y-1 text-sm'>Total operations<input className={field} required type='number' min={1} max={50} value={settings.actionsTotal} onChange={e => change('actionsTotal', Number(e.target.value))} /></label>
      <label className='space-y-1 text-sm'>In-app notifications<select className={field} value={settings.notificationPolicy} onChange={e => change('notificationPolicy', e.target.value as RecipeSettings['notificationPolicy'])}><option value='none'>None</option><option value='failures_and_approvals'>Failures and approval requests</option><option value='all'>All task outcomes</option></select></label>
    </div><p className='text-sm'>{template.triggerNote} Cost ceiling: $0. Editing pauses any previous policy; inspect and enable the new version separately.</p><div className='flex gap-2'><Button disabled={busy} type='submit'>Save for review</Button><Button type='button' variant='outline' disabled={busy} onClick={onClose}>Cancel</Button></div>
  </form>;
}

function ReportView({ value, close }: { value: RecipeReport; close: () => void }) {
  const report = value.report;
  return <section aria-label='Recipe report' className='space-y-3 rounded-lg border p-4'><div className='flex items-center justify-between gap-3'><h3 className='font-medium'>Stored report · {report?.state ?? 'Pending'}</h3><Button variant='outline' size='sm' onClick={close}>Close report</Button></div><p className='text-sm'>{report?.note ?? report?.coverage?.note}</p>{report?.truncated && <p className='text-sm font-medium'>Partial report: additional records are outside this bounded result.</p>}{report?.warnings?.map(w => <p key={w} className='text-sm'>{w}</p>)}
    {report?.items && <ul className='space-y-2'>{report.items.map(item => <li key={item.assetId} className='break-words text-sm'><Link className='underline' href={item.href}>{item.title ?? 'Untitled asset'}</Link> · {item.kind} · {item.tags.join(', ') || 'No tags'}</li>)}</ul>}
    {report?.data?.posts && <ul className='space-y-3'>{report.data.posts.map(post => <li key={post.jobId} className='rounded-md border p-3 text-sm'><p>{post.platform} · {post.publishedAt}</p><dl className='mt-1 flex flex-wrap gap-x-4'>{Object.entries(post.metrics).map(([name, metric]) => <div key={name}><dt className='inline'>{name}: </dt><dd className='inline'>{metric.value === null ? `Unavailable (${metric.availability})` : `${metric.value} ${metric.unit}`}</dd></div>)}</dl></li>)}</ul>}
    <details><summary className='cursor-pointer text-sm'>Exact report inputs and recorded result</summary><pre className='mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs'>{JSON.stringify(value, null, 2)}</pre></details>
  </section>;
}
