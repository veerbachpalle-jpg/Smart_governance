import { useEffect, useRef, useState, useMemo } from 'react';
import type { Complaint } from '@/lib/civic-types';

export const DEPARTMENT_PALETTE: Record<string, { color: string; label: string }> = {
  "Roads & Infrastructure": { color: "#ea580c", label: "Roads & Footpaths" },
  "Water & Drainage": { color: "#0284c7", label: "Water & Drainage" },
  "Electrical & Street Lighting": { color: "#eab308", label: "Street Lighting" },
  "Solid Waste Management": { color: "#16a34a", label: "Waste Management" },
  "Public Safety": { color: "#dc2626", label: "Public Safety" },
  "Stormwater & Drainage": { color: "#06b6d4", label: "Stormwater" },
  "Parks & Horticulture": { color: "#9333ea", label: "Parks" },
  "Awaiting assignment": { color: "#64748b", label: "Unassigned" },
};

export function getDepartmentColor(deptOrCategory?: string): string {
  if (!deptOrCategory) return "#64748b";
  const norm = deptOrCategory.toLowerCase();
  if (/road|footpath|pavement|bridge/.test(norm)) return "#ea580c"; // Orange
  if (/water|leak|supply|tap|pipe/.test(norm)) return "#0284c7"; // Sky Blue
  if (/drain|sewer|stormwater|flood/.test(norm)) return "#06b6d4"; // Cyan
  if (/light|electric|wire|lamp/.test(norm)) return "#eab308"; // Amber
  if (/waste|garbage|trash|sanitat|rubbish/.test(norm)) return "#16a34a"; // Green
  if (/park|garden|tree|horticult/.test(norm)) return "#9333ea"; // Purple
  if (/safe|danger|fire|police|manhole/.test(norm)) return "#dc2626"; // Red
  return "#64748b"; // Slate
}

interface Props {
  complaints?: Complaint[];
  lat?: number;
  lng?: number;
  onPick?: (lat: number, lng: number) => void;
  large?: boolean;
  showLegend?: boolean;
}

export default function LocationMap({
  complaints = [],
  lat = 12.969,
  lng = 77.639,
  onPick,
  large,
  showLegend = true,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [activeDeptFilter, setActiveDeptFilter] = useState<string | null>(null);

  // Group complaints by department for the legend
  const departmentStats = useMemo(() => {
    if (!complaints.length) return [];
    const counts: Record<string, number> = {};
    for (const c of complaints) {
      const dept = c.department || c.category || "Other";
      counts[dept] = (counts[dept] || 0) + 1;
    }
    return Object.entries(counts).map(([name, count]) => ({
      name,
      count,
      color: getDepartmentColor(name),
    }));
  }, [complaints]);

  const displayedComplaints = useMemo(() => {
    if (!activeDeptFilter) return complaints;
    return complaints.filter(
      (c) => (c.department || c.category) === activeDeptFilter,
    );
  }, [complaints, activeDeptFilter]);

  useEffect(() => {
    let disposed = false;
    let map: import('leaflet').Map | undefined;

    void import('leaflet').then((L) => {
      if (disposed || !container.current) return;

      const initialLat = displayedComplaints[0]?.lat ?? lat;
      const initialLng = displayedComplaints[0]?.lng ?? lng;

      map = L.map(container.current, {
        zoomControl: true,
        scrollWheelZoom: false,
      }).setView([initialLat, initialLng], displayedComplaints.length ? 13 : 15);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);

      if (displayedComplaints.length > 0) {
        const bounds = L.latLngBounds([]);

        displayedComplaints.forEach((row) => {
          if (!map || typeof row.lat !== 'number' || typeof row.lng !== 'number') return;
          const color = getDepartmentColor(row.department || row.category);

          const pinHtml = `
            <div style="
              width: 22px;
              height: 22px;
              border-radius: 50% 50% 50% 0;
              background-color: ${color};
              transform: rotate(-45deg);
              border: 2px solid #ffffff;
              box-shadow: 0 2px 5px rgba(0,0,0,0.35);
              display: flex;
              align-items: center;
              justify-content: center;
              cursor: pointer;
            ">
              <div style="
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background-color: #ffffff;
                transform: rotate(45deg);
              "></div>
            </div>
          `;

          const customIcon = L.divIcon({
            className: 'civic-dynamic-pin',
            html: pinHtml,
            iconSize: [22, 22],
            iconAnchor: [11, 22],
            popupAnchor: [0, -22],
          });

          const marker = L.marker([row.lat, row.lng], { icon: customIcon }).addTo(map);
          bounds.extend([row.lat, row.lng]);

          const popupContent = document.createElement('div');
          popupContent.style.minWidth = '200px';
          popupContent.style.fontFamily = 'inherit';
          popupContent.innerHTML = `
            <div style="padding: 2px;">
              <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background-color: ${color};"></span>
                <span style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: ${color}; letter-spacing: 0.5px;">${row.department || row.category}</span>
              </div>
              <div style="font-size: 13px; font-weight: 600; line-height: 1.35; margin-bottom: 4px; color: #0f172a;">${row.title}</div>
              <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">${row.address || row.ward || ''}</div>
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px; border-top: 1px solid #e2e8f0; padding-top: 8px;">
                <span style="font-size: 10px; padding: 2px 7px; border-radius: 9999px; background: #f1f5f9; font-weight: 600; color: #334155; text-transform: capitalize;">${row.status.replace('_', ' ')}</span>
                <a href="/complaints/${row.id}" style="font-size: 11px; color: #2563eb; font-weight: 600; text-decoration: none;">View Details &rarr;</a>
              </div>
            </div>
          `;
          marker.bindPopup(popupContent);
        });

        if (displayedComplaints.length > 1 && bounds.isValid()) {
          map.fitBounds(bounds, { padding: [25, 25], maxZoom: 15 });
        }
      } else {
        const defaultColor = getDepartmentColor();
        const pinHtml = `
          <div style="
            width: 22px;
            height: 22px;
            border-radius: 50% 50% 50% 0;
            background-color: ${defaultColor};
            transform: rotate(-45deg);
            border: 2px solid #ffffff;
            box-shadow: 0 2px 5px rgba(0,0,0,0.35);
            display: flex;
            align-items: center;
            justify-content: center;
          ">
            <div style="
              width: 7px;
              height: 7px;
              border-radius: 50%;
              background-color: #ffffff;
              transform: rotate(45deg);
            "></div>
          </div>
        `;
        const icon = L.divIcon({
          className: 'civic-dynamic-pin',
          html: pinHtml,
          iconSize: [22, 22],
          iconAnchor: [11, 22],
          popupAnchor: [0, -22],
        });

        const marker = L.marker([lat, lng], { icon, draggable: Boolean(onPick) }).addTo(map);
        if (onPick) {
          marker.on('dragend', () => {
            const pos = marker.getLatLng();
            onPick(pos.lat, pos.lng);
          });
          map.on('click', (event: import('leaflet').LeafletMouseEvent) => {
            marker.setLatLng(event.latlng);
            onPick(event.latlng.lat, event.latlng.lng);
          });
        }
      }

      setTimeout(() => map?.invalidateSize(), 150);
    });

    return () => {
      disposed = true;
      map?.remove();
    };
  }, [lat, lng, displayedComplaints, onPick]);

  return (
    <div className="w-full">
      <div
        ref={container}
        className={`map-container rounded-md overflow-hidden ${large ? 'large' : ''}`}
        aria-label="Complaint location map"
        role="region"
      />
      {showLegend && departmentStats.length > 0 && (
        <div className="mt-2.5 px-1">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
              Department Legend ({displayedComplaints.length} markers)
            </span>
            {activeDeptFilter && (
              <button
                type="button"
                onClick={() => setActiveDeptFilter(null)}
                className="text-[10px] text-primary hover:underline font-medium"
              >
                Show All
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {departmentStats.map((item) => {
              const isSelected = activeDeptFilter === item.name;
              return (
                <button
                  key={item.name}
                  type="button"
                  onClick={() =>
                    setActiveDeptFilter(isSelected ? null : item.name)
                  }
                  className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium border transition-colors ${
                    isSelected
                      ? 'border-primary bg-primary/10 text-foreground ring-1 ring-primary'
                      : 'border-border/80 bg-surface text-muted-foreground hover:bg-secondary hover:text-foreground'
                  }`}
                  title={`Filter by ${item.name}`}
                >
                  <span
                    className="size-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="truncate max-w-[140px]">{item.name}</span>
                  <span className="rounded-full bg-muted px-1.5 py-0.2 text-[9px] font-semibold">
                    {item.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

