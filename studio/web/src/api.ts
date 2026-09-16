export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {super(message); this.status=status; this.code=code;}
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const mutation = options.method && options.method !== 'GET';
  const headers = new Headers(options.headers);
  if (mutation) headers.set('X-Studio-Request','1');
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  let response: Response;
  try {response = await fetch(path, {...options, headers, credentials:'same-origin'});}
  catch {throw new ApiError(0,'offline','Studio is not reachable. Your unsaved input is still here. Start the local service, then retry.');}
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, data.error?.code || 'request_failed', data.error?.message || `Request failed (${response.status}). Your input has been kept.`);
  }
  return response.json() as Promise<T>;
}

export async function download(path: string, name: string) {
  let response: Response;
  try {response = await fetch(path, {credentials:'same-origin'});}
  catch {throw new Error('Studio is offline. Nothing was downloaded.');}
  if (!response.ok) {
    const data=await response.json().catch(()=>({}));
    throw new Error(data.error?.message||`Download failed (${response.status}). Reload the workspace if the service restarted.`);
  }
  saveBlob(await response.blob(),name);
}

export function saveBlob(blob: Blob, name: string) {
  const url=URL.createObjectURL(blob), anchor=document.createElement('a');
  anchor.href=url; anchor.download=name; document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url),1000);
}
