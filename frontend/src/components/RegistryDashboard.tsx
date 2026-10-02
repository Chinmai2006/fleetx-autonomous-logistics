import React, { useState, useEffect, useCallback } from 'react';
import { 
  Bot,
  Truck,
  Plane,
  RefreshCw,
  Radio,
  XCircle,
  Activity
} from 'lucide-react';

interface AgentState {
  battery_pct: number;
  status: string;
  is_available: boolean;
}

interface Agent {
  agent_id: string;
  agent_type: string;
  capabilities: string[];
  status: string;
  state: AgentState;
  last_seen: number;
  registered_at: number;
}

interface ManagedAgent {
  agent_id: string;
  agent_type: string;
  process_state: string;
  archived: boolean;
}

export const RegistryDashboard: React.FC<{ roleToken?: string }> = ({ roleToken = '' }) => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [managedAgents, setManagedAgents] = useState<ManagedAgent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [manageError, setManageError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    try {
      let response: Response;
      try {
        response = await fetch('/api/v1/agents');
      } catch {
        response = await fetch('http://localhost:8000/api/v1/agents');
      }

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: Agent[] = await response.json();
      setAgents(data);
      if (roleToken) {
        const managedResponse = await fetch('/api/v1/agents/managed', { headers: { Authorization: `Bearer ${roleToken}` } });
        if (managedResponse.ok) setManagedAgents(await managedResponse.json());
      }
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to connect to Registry API');
    } finally {
      setLoading(false);
    }
  }, [roleToken]);

  useEffect(() => {
    fetchAgents();
    const interval = setInterval(fetchAgents, 3000);
    return () => clearInterval(interval);
  }, [fetchAgents]);

  const getAgentIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case 'drone': return <Plane className="w-5 h-5 text-cyan-400" />;
      case 'vehicle': 
      case 'agv': return <Truck className="w-5 h-5 text-indigo-400" />;
      default: return <Bot className="w-5 h-5 text-emerald-400" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const isOffline = status === 'OFFLINE';
    const isIdle = status === 'IDLE';
    const isBusy = status === 'BUSY';

    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${
        isOffline ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' :
        isIdle ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
        isBusy ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' :
        'bg-slate-500/10 text-slate-400 border-slate-500/20'
      }`}>
        <span className={`w-1.5 h-1.5 mr-1.5 rounded-full ${
          isOffline ? 'bg-rose-400' :
          isIdle ? 'bg-emerald-400 animate-pulse' :
          isBusy ? 'bg-amber-400' :
          'bg-slate-400'
        }`} />
        {status}
      </span>
    );
  };

  const activeAgents = agents.filter((agent) =>
    agent.status !== 'OFFLINE'
    && agent.status !== 'ERROR'
    && Date.now() / 1000 - agent.last_seen <= 15
  );
  const historicalAgents = agents.filter((agent) => !activeAgents.includes(agent));
  const coordinationStages = [
    { label: 'ROBOT', types: ['robot', 'warehouse_robot'], description: 'Origin handling' },
    { label: 'AGV', types: ['agv', 'vehicle'], description: 'Ground transfer' },
    { label: 'DRONE', types: ['drone'], description: 'Final delivery' },
  ];

  const renderAgentCard = (agent: Agent, historical = false) => (
    <article key={agent.agent_id} className="rounded-md border border-slate-800 bg-slate-900/70 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-slate-800 bg-slate-950">
            {getAgentIcon(agent.agent_type)}
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-100">{agent.agent_id}</h3>
            <p className="text-[10px] uppercase text-slate-500">{agent.agent_type}</p>
          </div>
        </div>
        <span className={`shrink-0 text-[10px] font-medium ${historical ? 'text-slate-500' : 'text-emerald-300'}`}>
          <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${historical ? 'bg-slate-500' : 'bg-emerald-400'}`} />
          {historical ? 'HISTORICAL' : 'ONLINE'}
        </span>
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-slate-800 pt-2 text-[11px]">
        <span className="text-slate-400">Battery <strong className="font-medium text-slate-200">{agent.state.battery_pct.toFixed(0)}%</strong></span>
        {getStatusBadge(agent.status)}
      </div>
      <div className="mt-2">
        <p className="mb-1 text-[9px] font-semibold uppercase text-slate-600">Capabilities</p>
        <p className="text-[10px] leading-4 text-slate-400">
          {agent.capabilities.map((capability) => capability.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())).join(' · ') || 'None advertised'}
        </p>
      </div>
    </article>
  );

  const createAgent = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parseList = (field: string) => String(form.get(field) || '').split(',').map((value) => value.trim()).filter(Boolean);
    let metadata: Record<string, unknown> = {};
    try {
      metadata = JSON.parse(String(form.get('metadata') || '{}')) as Record<string, unknown>;
      if (!metadata || Array.isArray(metadata) || typeof metadata !== 'object') throw new Error('Metadata must be a JSON object');
    } catch {
      setManageError('Metadata must be valid JSON object data.');
      return;
    }
    setSubmitting(true);
    setManageError(null);
    try {
      const response = await fetch('/api/v1/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${roleToken}` },
        body: JSON.stringify({
          agent_id: form.get('agent_id'),
          agent_type: form.get('agent_type'),
          capabilities: parseList('capabilities'),
          payload_capacity_kg: Number(form.get('payload_capacity_kg')),
          battery_pct: Number(form.get('battery_pct')),
          location: { x: Number(form.get('location_x')), y: Number(form.get('location_y')), z: Number(form.get('location_z')) },
          available: form.get('available') === 'on',
          supported_operations: parseList('supported_operations'),
          operational_constraints: {
            minimum_battery_pct: Number(form.get('minimum_battery_pct')),
            maximum_distance_km: form.get('maximum_distance_km') ? Number(form.get('maximum_distance_km')) : null,
            excluded_task_types: parseList('excluded_task_types'),
          },
          metadata,
          mqtt_password: form.get('mqtt_password') || null,
        }),
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      (event.currentTarget as HTMLFormElement).reset();
      setShowAddForm(false);
      await fetchAgents();
    } catch (requestError) {
      setManageError(requestError instanceof Error ? requestError.message : 'Agent registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  const manageAgent = async (agentId: string, action: 'activate' | 'deactivate' | 'archive') => {
    setManageError(null);
    try {
      const response = await fetch(`/api/v1/agents/${encodeURIComponent(agentId)}${action === 'archive' ? '' : `/${action}`}`, {
        method: action === 'archive' ? 'DELETE' : 'POST',
        headers: { Authorization: `Bearer ${roleToken}` },
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      await fetchAgents();
    } catch (requestError) {
      setManageError(requestError instanceof Error ? requestError.message : 'Agent operation failed');
    }
  };

  return (
    <section className="space-y-3" aria-labelledby="fleet-heading">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md border border-cyan-900/70 bg-cyan-950/40 text-cyan-300">
            <Radio className="h-4 w-4" />
          </div>
          <div>
            <h2 id="fleet-heading" className="text-sm font-semibold text-white">Active Fleet</h2>
            <p className="text-[11px] text-slate-500">{activeAgents.length} online · {agents.length} known</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => { setShowAddForm(!showAddForm); setManageError(null); }} className="rounded border border-cyan-900 px-2.5 py-1.5 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-950/40">{showAddForm ? 'CANCEL' : 'ADD AGENT'}</button>
          <button onClick={fetchAgents} disabled={loading} aria-label="Refresh fleet" className="rounded border border-slate-800 p-1.5 text-slate-400 transition hover:bg-slate-900 hover:text-cyan-200 disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-cyan-300' : ''}`} />
          </button>
        </div>
      </div>

      {showAddForm && (
        <form onSubmit={createAgent} className="grid grid-cols-2 gap-2 rounded-md border border-cyan-900/60 bg-slate-900/70 p-3 sm:grid-cols-4">
          <label className="text-[10px] text-slate-500">Agent ID<input name="agent_id" required maxLength={64} className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Type<select name="agent_type" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"><option>ROBOT</option><option>AGV</option><option>DRONE</option></select></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Capabilities, comma separated<input name="capabilities" required placeholder="bin_picking, barcode_scanning" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Payload capacity (kg)<input name="payload_capacity_kg" type="number" min="0" step="0.1" required defaultValue="25" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Battery (%)<input name="battery_pct" type="number" min="0" max="100" required defaultValue="100" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Local X<input name="location_x" type="number" step="any" required defaultValue="0" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Local Y<input name="location_y" type="number" step="any" required defaultValue="0" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Local Z<input name="location_z" type="number" step="any" required defaultValue="0" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Minimum battery constraint (%)<input name="minimum_battery_pct" type="number" min="0" max="100" defaultValue="20" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Maximum route distance (km)<input name="maximum_distance_km" type="number" min="0" step="any" placeholder="No limit" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Supported operations<input name="supported_operations" placeholder="pick_item, sort_parcel" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Excluded task types<input name="excluded_task_types" placeholder="hazmat" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="flex items-end gap-2 pb-2 text-[10px] text-slate-300"><input name="available" type="checkbox" defaultChecked className="rounded border-slate-600 bg-slate-950" />Available at startup</label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">MQTT agent password (optional)<input name="mqtt_password" type="password" autoComplete="new-password" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Metadata JSON<input name="metadata" defaultValue="{}" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <div className="flex items-end"><button disabled={submitting || !roleToken} className="w-full rounded bg-cyan-700 px-3 py-2 text-[10px] font-semibold text-white disabled:opacity-40">{submitting ? 'STARTING...' : 'REGISTER AGENT'}</button></div>
          {!roleToken && <p className="col-span-2 self-end text-[10px] text-amber-300 sm:col-span-4">Admin bearer token required. Configure access in System.</p>}
        </form>
      )}
      {manageError && <p role="alert" className="rounded border border-rose-900/70 bg-rose-950/30 px-3 py-2 text-[10px] text-rose-200">{manageError}</p>}

      <div className="rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2.5">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Fleet coordination</h3>
          <span className="text-[10px] text-slate-600">Live agent presence</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {coordinationStages.map((stage, index) => {
            const agent = activeAgents.find((candidate) => stage.types.includes(candidate.agent_type.toLowerCase()));
            return (
              <div key={stage.label} className="flex items-center gap-2">
                <div className={`min-w-0 flex-1 border-l-2 pl-2.5 ${agent ? 'border-emerald-700' : 'border-slate-700'}`}>
                  <p className="text-[10px] font-semibold text-slate-300">{stage.label}</p>
                  <p className="truncate text-[10px] text-slate-500">{agent ? `${agent.agent_id} · ${agent.status}` : 'No active agent'} · {stage.description}</p>
                </div>
                {index < coordinationStages.length - 1 && <span className="hidden text-slate-700 sm:inline">→</span>}
              </div>
            );
          })}
        </div>
      </div>

      {error ? (
        <div className="flex items-center gap-2 rounded-md border border-rose-900/70 bg-rose-950/30 p-3 text-xs text-rose-200">
          <XCircle className="h-4 w-4 text-rose-400" />
          <span>{error}</span>
        </div>
      ) : activeAgents.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-800 px-4 py-5 text-center">
          <Activity className="mx-auto mb-2 h-5 w-5 text-slate-600" />
          <p className="text-xs text-slate-400">No agents currently reporting</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {activeAgents.map((agent) => renderAgentCard(agent))}
        </div>
      )}

      {historicalAgents.length > 0 && (
        <details className="rounded-md border border-slate-800 bg-slate-900/40">
          <summary className="cursor-pointer px-3 py-2 text-[11px] text-slate-500 hover:text-slate-300">
            Show offline / historical agents ({historicalAgents.length})
          </summary>
          <div className="grid grid-cols-1 gap-2 border-t border-slate-800 p-2 sm:grid-cols-2 xl:grid-cols-3">
            {historicalAgents.map((agent) => renderAgentCard(agent, true))}
          </div>
        </details>
      )}

      {roleToken && managedAgents.length > 0 && (
        <details className="rounded-md border border-slate-800 bg-slate-900/40">
          <summary className="cursor-pointer px-3 py-2 text-[11px] text-slate-500">Managed agent processes ({managedAgents.length})</summary>
          <div className="divide-y divide-slate-800 border-t border-slate-800">
            {managedAgents.map((agent) => (
              <div key={agent.agent_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[10px]">
                <span className="text-slate-300">{agent.agent_id} · {agent.agent_type} · {agent.process_state}{agent.archived ? ' · ARCHIVED' : ''}</span>
                <div className="flex gap-1.5">
                  <button type="button" disabled={agent.archived} onClick={() => manageAgent(agent.agent_id, agent.process_state === 'RUNNING' ? 'deactivate' : 'activate')} className="rounded border border-slate-700 px-2 py-1 text-slate-300 disabled:opacity-40">{agent.process_state === 'RUNNING' ? 'DEACTIVATE' : 'ACTIVATE'}</button>
                  {!agent.archived && <button type="button" onClick={() => manageAgent(agent.agent_id, 'archive')} className="rounded border border-rose-900 px-2 py-1 text-rose-300">ARCHIVE</button>}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
};
