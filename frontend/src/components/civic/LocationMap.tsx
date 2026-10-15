import { useEffect, useRef } from 'react';
import type { Complaint } from '@/lib/civic-types';
interface Props { complaints?: Complaint[]; lat?: number; lng?: number; onPick?: (lat: number, lng: number) => void; large?: boolean }
export default function LocationMap({ complaints = [], lat = 12.969, lng = 77.639, onPick, large }: Props) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let map: import('leaflet').Map | undefined;
    void import('leaflet').then(L => {
      if (disposed || !container.current) return;
      map = L.map(container.current, { zoomControl: true, scrollWheelZoom: false }).setView([lat, lng], complaints.length ? 13 : 15);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 19 }).addTo(map);
      const icon = L.divIcon({ className: 'civic-map-pin', iconSize: [17, 17], iconAnchor: [8, 8] });
      if (complaints.length) complaints.forEach(row => { if (map) { const popup = document.createElement('span'); popup.textContent = row.title; L.marker([row.lat, row.lng], { icon }).addTo(map).bindPopup(popup); } });
      else {
        const marker = L.marker([lat, lng], { icon, draggable: Boolean(onPick) }).addTo(map);
        if (onPick) {
          marker.on('dragend', () => { const pos = marker.getLatLng(); onPick(pos.lat, pos.lng); });
          map.on('click', (event: import('leaflet').LeafletMouseEvent) => { marker.setLatLng(event.latlng); onPick(event.latlng.lat, event.latlng.lng); });
        }
      }
      setTimeout(() => map?.invalidateSize(), 100);
    });
    return () => { disposed = true; map?.remove(); };
  }, [lat, lng, complaints, onPick]);
  return <div ref={container} className={`map-container ${large ? 'large' : ''}`} aria-label="Complaint location map" role="region" />;
}
