import { sampleComplaints } from './civic-data';
import type { Complaint, NewComplaint, Status, Tokens } from './civic-types';
export function getIsDemo(): boolean {
  if (typeof window === 'undefined') return true;
  const saved = localStorage.getItem('civic-mode');
  if (saved === 'demo' || saved === 'original') return saved === 'demo';
  return import.meta.env['VITE_USE_MOCKS'] === 'true' || !import.meta.env['VITE_API_BASE_URL'];
}

export let isDemo = getIsDemo();

export function setDemoMode(value: boolean) {
  isDemo = value;
  if (typeof window !== 'undefined') {
    localStorage.setItem('civic-mode', value ? 'demo' : 'original');
    window.dispatchEvent(new CustomEvent('civic-mode-change', { detail: value }));
  }
}

const base = import.meta.env['VITE_API_BASE_URL']?.replace(/\/$/, '') ?? '';
let tokens: Tokens | null = null;
let refreshInFlight: Promise<void> | null = null;
let demoRows = sampleComplaints.map(row => ({ ...row }));
export class ApiError extends Error { constructor(message: string, public code: number) { super(message); } }

export function setTokens(value: any) {
  if (!value) {
    tokens = null;
    return;
  }
  const accessToken = value.accessToken || value.access_token || '';
  const refreshToken = value.refreshToken || value.refresh_token || '';
  let role: Role | 'citizen' = value.role || 'citizen';
  if (accessToken) {
    try {
      const parts = accessToken.split('.');
      if (parts.length === 3) {
        const payload = JSON.parse(atob(parts[1]));
        if (payload.role) role = payload.role;
      }
    } catch {
      // fallback
    }
  }
  tokens = { accessToken, refreshToken, role };
}

export function getSession() { return tokens; }
async function refreshSession() {
  if (!tokens?.refreshToken) throw new ApiError('Your session has expired. Please sign in again.', 401);
  const response = await fetch(`${base}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: tokens.refreshToken, refreshToken: tokens.refreshToken }),
  });
  if (!response.ok) { tokens = null; throw new ApiError('Your session has expired. Please sign in again.', 401); }
  const data = await response.json();
  setTokens(data);
}
export async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  if (!base) throw new ApiError('The municipal service is not connected yet. Please try again once it is available.', 503);
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (tokens) headers.set('Authorization', `Bearer ${tokens.accessToken}`);
  let response: Response;
  try { response = await fetch(`${base}${path}`, { ...options, headers }); } catch { throw new ApiError('Connection lost. Your draft is safe. Check your connection and try again.', 0); }
  if (response.status === 401 && retry && tokens) {
    refreshInFlight ??= refreshSession().finally(() => { refreshInFlight = null; });
    await refreshInFlight;
    return request<T>(path, options, false);
  }
  if (!response.ok) {
    const messages: Record<number, string> = { 401: 'Please sign in to continue.', 403: 'Your role does not have permission for this action.', 404: 'No complaint was found with this tracking ID.', 409: 'This case was updated by someone else. Refresh before continuing.', 422: 'Please check the information and try again.', 429: 'Too many requests. Please wait a moment and retry.' };
    throw new ApiError(messages[response.status] ?? 'The service is temporarily unavailable. Please try again.', response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
const delay = () => new Promise<void>(resolve => setTimeout(resolve, 250));
export const civicApi = {
  async list(): Promise<Complaint[]> { if (!isDemo) return request('/complaints'); await delay(); return demoRows; },
  async create(input: NewComplaint, key: string): Promise<Complaint> {
    if (!isDemo) return request('/complaints', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(input) });
    await delay();
    const row: Complaint = { ...input, id: `BLR-2026-${String(1500 + demoRows.length).padStart(5, '0')}`, ward: 'Ward assignment pending', date: new Date().toISOString().slice(0, 10), status: 'submitted', department: 'Awaiting assignment', priority: 'Normal', evidenceVerified: false, activity: [{ title: 'Report received', note: 'Awaiting human triage and department assignment.', department: 'Citizen services', date: new Date().toISOString().slice(0, 10), public: true }] };
    demoRows = [row, ...demoRows]; return row;
  },
  async update(id: string, changes: Partial<Complaint>, action: string): Promise<Complaint> {
    if (!isDemo) return request(`/complaints/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: JSON.stringify(changes), headers: { 'Idempotency-Key': crypto.randomUUID() } });
    await delay(); const row = demoRows.find(item => item.id === id); if (!row) throw new ApiError('Complaint not found.', 404);
    const next = { ...row, ...changes }; demoRows = demoRows.map(item => item.id === id ? next : item); return next;
  },
  async transition(id: string, status: Status, note: string, isPublic: boolean): Promise<Complaint> {
    const row = demoRows.find(item => item.id === id);
    return this.update(id, { status, activity: [{ title: note, note, department: row?.department ?? 'Assigned officer', date: new Date().toISOString().slice(0, 10), public: isPublic }, ...(row?.activity ?? [])] }, 'transition');
  },
};