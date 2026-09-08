import type { Mode, Snapshot } from './state';
export class ApiError extends Error { constructor(public status:number, public body?:unknown){super(detailFrom(body))} }
export function detailFrom(value:unknown, fallback='Request failed') { if(value instanceof ApiError)return detailFrom(value.body,value.message);return typeof value==='object' && value && 'detail' in value && typeof value.detail==='string' ? value.detail : fallback; }
const API_ROOT=(import.meta.env.VITE_API_ROOT as string|undefined)?.replace(/\/$/,'') ?? 'http://localhost:8000';
async function request<T>(path:string, init:RequestInit={}, token?:string):Promise<T>{
  const headers=new Headers(init.headers); headers.set('Content-Type','application/json'); if(token) headers.set('Authorization',`Bearer ${token}`);
  let response:Response; try { response=await fetch(`${API_ROOT}${path}`,{...init,headers}); } catch { throw new ApiError(0,{detail:'Cannot reach the session service. Check that the API is running.'}); }
  if(!response.ok){let body:unknown;try{body=await response.json()}catch{}throw new ApiError(response.status,body ?? {detail:`Request failed (${response.status})`})}
  return response.status===204 ? undefined as T : response.json();
}
export const api={
 health:()=>request<{mode:string;live_ready:boolean;missing_config:string[];demo_enabled:boolean}>('/api/health'),
 create:(mode:Mode)=>request<{session_id:string;token:string;snapshot:Snapshot}>('/api/sessions',{method:'POST',body:JSON.stringify({mode})}),
 snapshot:(id:string,token:string)=>request<Snapshot>(`/api/sessions/${id}`,{},token),
 turn:(id:string,token:string,text:string,event_id=crypto.randomUUID())=>request<Snapshot>(`/api/sessions/${id}/turn`,{method:'POST',body:JSON.stringify({text,event_id})},token),
 control:(id:string,token:string,action:string)=>request<Snapshot>(`/api/sessions/${id}/control`,{method:'POST',body:JSON.stringify({action})},token),
 faults:(id:string,token:string,body:unknown)=>request<Snapshot>(`/api/sessions/${id}/faults`,{method:'POST',body:JSON.stringify(body)},token),
 playback:(id:string,token:string,response_id:string,status:string)=>request<Snapshot>(`/api/sessions/${id}/playback`,{method:'POST',body:JSON.stringify({response_id,status})},token),
 liveToken:(id:string,token:string)=>request<{url:string;token:string;room:string}>(`/api/sessions/${id}/token`,{method:'POST'},token)
};
