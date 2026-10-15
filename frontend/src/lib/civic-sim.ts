import { useEffect, useState } from 'react';

const KEY = 'civic-simulation';
const EVENT = 'civic-simulation-change';

function read(): string[] {
  try { const raw = localStorage.getItem(KEY); const parsed: unknown = raw ? JSON.parse(raw) : []; return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []; } catch { return []; }
}

/** Shared failure-simulation state, persisted per device and synced across the staff console. */
export function useSimulation(): [string[], (next: string[]) => void] {
  const [value, setValue] = useState<string[]>([]);
  useEffect(() => { const sync = () => setValue(read()); sync(); window.addEventListener(EVENT, sync); window.addEventListener('storage', sync); return () => { window.removeEventListener(EVENT, sync); window.removeEventListener('storage', sync); }; }, []);
  const update = (next: string[]) => { try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage unavailable */ } setValue(next); window.dispatchEvent(new Event(EVENT)); };
  return [value, update];
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(true);
  useEffect(() => { const sync = () => setOnline(navigator.onLine); sync(); window.addEventListener('online', sync); window.addEventListener('offline', sync); return () => { window.removeEventListener('online', sync); window.removeEventListener('offline', sync); }; }, []);
  return online;
}

export function distanceMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const r = 6371000, toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}
