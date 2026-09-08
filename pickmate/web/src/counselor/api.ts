export type Mode = 'live' | 'text';
export type Message = { id: string; role: 'user' | 'assistant'; text: string; utc: string; status: string };
export type Credential = { id: string; token: string };
export type Snapshot = {
  session_id: string; revision: number; mode: Mode; ended: boolean; paused: boolean;
  thinking: boolean; user_speaking: boolean; error: string | null;
  messages: Message[]; speech: { response_id: string; status: string; text: string } | null;
  provider: { status: string }; worker_epoch: number;
};
export type Health = { product: string; live_ready: boolean; conversation_ready: boolean };
export class RequestError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function request<T>(path: string, body?: unknown, credential?: Credential): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (credential) headers.Authorization = `Bearer ${credential.token}`;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method: body === undefined ? 'GET' : 'POST', headers,
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
  } catch { throw new RequestError(0, 'The connection was interrupted. Please try again.'); }
  const data = await response.json();
  if (!response.ok) throw new RequestError(response.status, typeof data.detail === 'string' ? data.detail : 'That request could not be completed.');
  return data;
}
export const route = (credential: Credential, suffix = '') => `/sessions/${credential.id}${suffix}`;
