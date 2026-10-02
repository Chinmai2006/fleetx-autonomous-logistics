import React, { useEffect, useRef, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix Leaflet default icon paths broken by Vite bundling
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

export interface LocalLocation { x: number; y: number; z: number; }

export interface FleetMapAgent {
  agent_id: string;
  agent_type: string;
  capabilities: string[];
  status: string;
  last_seen: number;
  state: {
    battery_pct: number;
    status: string;
    is_available: boolean;
    current_task_id: string | null;
    location: LocalLocation;
  };
}

export interface FleetMapTask {
  task_id: string;
  origin: string;
  destination: string;
  status: string;
  origin_location?: LocalLocation | null;
  destination_location?: LocalLocation | null;
  waypoints?: LocalLocation[];
}

export interface GeoCoord { lat: number; lng: number; }

export interface FleetMapProps {
  agents: FleetMapAgent[];
  tasks: FleetMapTask[];
  selectedAgentId?: string | null;
  onSelectAgent?: (agentId: string) => void;
  className?: string;
  warehouseAnchor?: GeoCoord;
  localScale?: number;
}

// ── Default warehouse anchor ─────────────────────────────────────────────────
// Demo warehouse at a real location. Agents with zero coords are placed here.
const DEFAULT_ANCHOR: GeoCoord = { lat: 37.7749, lng: -122.4194 };

// ── Coordinate helpers ────────────────────────────────────────────────────────
function localToGeo(loc: LocalLocation, anchor: GeoCoord, scale: number): L.LatLngTuple {
  const lat = anchor.lat + (loc.y * scale) / 111320;
  const lng = anchor.lng + (loc.x * scale) / (111320 * Math.cos((anchor.lat * Math.PI) / 180));
  return [lat, lng];
}

function agentFill(status: string): string {
  if (status === 'OFFLINE' || status === 'ERROR') return '#fb7185';
  if (status === 'BUSY') return '#fbbf24';
  if (status === 'CHARGING') return '#60a5fa';
  return '#34d399';
}

function agentTypeLabel(t: string): string {
  const l = t.toLowerCase();
  if (l === 'drone') return '✈';
  if (l === 'agv' || l === 'vehicle') return '🚛';
  return '🤖';
}

// ── Fit bounds helper ─────────────────────────────────────────────────────────
function FitBounds({ positions }: { positions: L.LatLngTuple[] }) {
  const map = useMap();
  const prev = useRef('');
  useEffect(() => {
    const key = JSON.stringify(positions);
    if (key === prev.current) return;
    prev.current = key;
    if (positions.length === 0) return;
    if (positions.length === 1) {
      map.setView(positions[0], 15, { animate: false });
    } else {
      try {
        map.fitBounds(L.latLngBounds(positions).pad(0.3), { animate: false, maxZoom: 17 });
      } catch {
        map.setView(positions[0], 14, { animate: false });
      }
    }
  });
  return null;
}

// ── Local warehouse fit helper ────────────────────────────────────────────────
function FitSimple({ positions }: { positions: L.LatLngTuple[] }) {
  const map = useMap();
  const prev = useRef('');
  useEffect(() => {
    const key = JSON.stringify(positions);
    if (key === prev.current) return;
    prev.current = key;
    if (positions.length === 0) { map.setView([0, 0], 0); return; }
    try {
      map.fitBounds(L.latLngBounds(positions).pad(0.3), { animate: false, maxZoom: 4 });
    } catch {
      map.setView([positions[0][0], positions[0][1]], 1, { animate: false });
    }
  });
  return null;
}

// ── Main component ────────────────────────────────────────────────────────────
export const FleetMap: React.FC<FleetMapProps> = ({
  agents,
  tasks,
  selectedAgentId,
  onSelectAgent,
  className = 'h-[360px]',
  warehouseAnchor,
  localScale = 1,
}) => {
  const [mapMode, setMapMode] = useState<'geo' | 'local'>('geo');
  const anchor = warehouseAnchor ?? DEFAULT_ANCHOR;

  // Routes: tasks that carry explicit coordinates
  const routes = tasks.flatMap(task => {
    if (!task.origin_location || !task.destination_location) return [];
    const pts: LocalLocation[] = [
      task.origin_location,
      ...(task.waypoints ?? []),
      task.destination_location,
    ];
    return [{ task, pts }];
  });

  // ── GEOGRAPHIC MODE ───────────────────────────────────────────────────────
  if (mapMode === 'geo') {
    const toGeo = (loc: LocalLocation): L.LatLngTuple => localToGeo(loc, anchor, localScale);
    const agentPositions = agents.map(a => toGeo(a.state.location));
    const routePositions = routes.flatMap(r => r.pts.map(toGeo));
    const allPositions: L.LatLngTuple[] = [...agentPositions, ...routePositions];
    const anyNonZero = agents.some(a => a.state.location.x !== 0 || a.state.location.y !== 0)
      || routes.length > 0;

    return (
      <div
        className={`relative rounded-md border border-slate-800 ${className}`}
        style={{ minHeight: 200 }}
      >
        {/* Leaflet requires a non-zero explicit height on the container element */}
        <div style={{ position: 'absolute', inset: 0 }}>
          <MapContainer
            key="geo-map"
            center={[anchor.lat, anchor.lng]}
            zoom={13}
            scrollWheelZoom
            zoomControl
            style={{ height: '100%', width: '100%' }}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {allPositions.length > 0 && <FitBounds positions={allPositions} />}

            {/* Mission route polylines */}
            {routes.map(({ task, pts }) => (
              <Polyline
                key={task.task_id}
                positions={pts.map(toGeo)}
                pathOptions={{
                  color: task.status === 'COMPLETED' ? '#6ee7b7' : '#22d3ee',
                  weight: 3,
                  opacity: 0.9,
                  dashArray: task.status === 'COMPLETED' ? '6 8' : undefined,
                }}
              >
                <Popup>
                  <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    <strong>{task.task_id}</strong><br />
                    {task.origin} → {task.destination}<br />
                    <span style={{ color: task.status === 'COMPLETED' ? '#10b981' : task.status === 'FAILED' ? '#f43f5e' : '#f59e0b' }}>
                      {task.status}
                    </span>
                  </div>
                </Popup>
              </Polyline>
            ))}

            {/* Agent markers */}
            {agents.map((agent, i) => (
              <CircleMarker
                key={agent.agent_id}
                center={agentPositions[i]}
                radius={selectedAgentId === agent.agent_id ? 11 : 8}
                pathOptions={{
                  color: selectedAgentId === agent.agent_id ? '#e0f2fe' : '#0f172a',
                  weight: selectedAgentId === agent.agent_id ? 3 : 1.5,
                  fillColor: agentFill(agent.status),
                  fillOpacity: 0.95,
                }}
                eventHandlers={{ click: () => onSelectAgent?.(agent.agent_id) }}
              >
                <Popup>
                  <div style={{ fontFamily: 'monospace', fontSize: 12, minWidth: 160 }}>
                    <strong>{agentTypeLabel(agent.agent_type)} {agent.agent_id}</strong><br />
                    {agent.agent_type.toUpperCase()} · <b>{agent.status}</b><br />
                    Battery {agent.state.battery_pct.toFixed(0)}%<br />
                    {agent.state.current_task_id
                      ? <span>Mission: {agent.state.current_task_id}</span>
                      : <span style={{ color: '#94a3b8' }}>No active mission</span>}<br />
                    <span style={{ fontSize: 10, color: '#94a3b8' }}>
                      {anyNonZero ? 'Simulated coordinates' : `Warehouse anchor (no GPS)`}
                    </span>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>

        {/* Overlays on top of the map */}
        <div className="pointer-events-none absolute left-2 top-2 z-[1000] rounded border border-slate-700/80 bg-slate-950/90 px-2 py-1 text-[9px] uppercase tracking-wide text-slate-400">
          {anyNonZero ? 'Simulated coords → geographic projection' : `Anchor · ${anchor.lat.toFixed(4)}, ${anchor.lng.toFixed(4)}`}
        </div>

        <div className="pointer-events-auto absolute right-2 top-2 z-[1000] flex gap-1">
          <button
            onClick={() => setMapMode('geo')}
            className="rounded border border-cyan-600 bg-cyan-900/80 px-2 py-1 text-[9px] font-semibold text-cyan-200"
          >GEOGRAPHIC</button>
          <button
            onClick={() => setMapMode('local')}
            className="rounded border border-slate-700 bg-slate-950/80 px-2 py-1 text-[9px] font-semibold text-slate-400 hover:text-slate-200"
          >WAREHOUSE</button>
        </div>

        {agents.length === 0 && (
          <div className="pointer-events-none absolute inset-x-0 bottom-6 z-[1000] flex justify-center">
            <span className="rounded border border-slate-700 bg-slate-950/90 px-3 py-1.5 text-[10px] text-slate-400">
              No active agents — add agents to see fleet positions
            </span>
          </div>
        )}
      </div>
    );
  }

  // ── WAREHOUSE / LOCAL MODE ────────────────────────────────────────────────
  const localAgentPositions = agents.map(a => [a.state.location.y, a.state.location.x] as L.LatLngTuple);
  const localRoutePts = routes.flatMap(r => r.pts.map(p => [p.y, p.x] as L.LatLngTuple));
  const localAll: L.LatLngTuple[] = [...localAgentPositions, ...localRoutePts];

  return (
    <div
      className={`relative rounded-md border border-slate-800 ${className}`}
      style={{ minHeight: 200 }}
    >
      <div style={{ position: 'absolute', inset: 0 }}>
        <MapContainer
          key="local-map"
          crs={L.CRS.Simple}
          center={[0, 0]}
          zoom={0}
          minZoom={-8}
          maxZoom={8}
          scrollWheelZoom
          zoomControl
          style={{ height: '100%', width: '100%', background: '#0b1118' }}
        >
          <FitSimple positions={localAll} />

          {routes.map(({ task, pts }) => (
            <Polyline
              key={task.task_id}
              positions={pts.map(p => [p.y, p.x] as L.LatLngTuple)}
              pathOptions={{
                color: task.status === 'COMPLETED' ? '#6ee7b7' : '#22d3ee',
                weight: 3,
                opacity: 0.9,
                dashArray: task.status === 'COMPLETED' ? '6 8' : undefined,
              }}
            >
              <Popup>
                <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  <strong>{task.task_id}</strong><br />
                  {task.origin} → {task.destination}<br />
                  {task.status}
                </div>
              </Popup>
            </Polyline>
          ))}

          {agents.map((agent, i) => (
            <CircleMarker
              key={agent.agent_id}
              center={localAgentPositions[i]}
              radius={selectedAgentId === agent.agent_id ? 10 : 7}
              pathOptions={{
                color: selectedAgentId === agent.agent_id ? '#a5f3fc' : '#0b1118',
                weight: 2,
                fillColor: agentFill(agent.status),
                fillOpacity: 0.95,
              }}
              eventHandlers={{ click: () => onSelectAgent?.(agent.agent_id) }}
            >
              <Popup>
                <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  <strong>{agentTypeLabel(agent.agent_type)} {agent.agent_id}</strong><br />
                  {agent.agent_type.toUpperCase()} · {agent.status}<br />
                  Battery {agent.state.battery_pct.toFixed(0)}%<br />
                  {agent.state.current_task_id ?? 'No active mission'}
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>

      <div className="pointer-events-none absolute left-2 top-2 z-[1000] rounded border border-slate-700/80 bg-slate-950/90 px-2 py-1 text-[9px] uppercase tracking-wide text-slate-400">
        Warehouse view · local coordinates
      </div>

      <div className="pointer-events-auto absolute right-2 top-2 z-[1000] flex gap-1">
        <button
          onClick={() => setMapMode('geo')}
          className="rounded border border-slate-700 bg-slate-950/80 px-2 py-1 text-[9px] font-semibold text-slate-400 hover:text-slate-200"
        >GEOGRAPHIC</button>
        <button
          onClick={() => setMapMode('local')}
          className="rounded border border-cyan-600 bg-cyan-900/80 px-2 py-1 text-[9px] font-semibold text-cyan-200"
        >WAREHOUSE</button>
      </div>

      {localAll.length === 0 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-6 z-[1000] flex justify-center">
          <span className="rounded border border-slate-700 bg-slate-950/90 px-3 py-1.5 text-[10px] text-slate-400">
            No coordinates — provide x/y when creating agents/missions
          </span>
        </div>
      )}
    </div>
  );
};
