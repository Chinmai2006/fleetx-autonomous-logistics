import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ClipboardList, Plus, RefreshCw, Radio, XCircle, Zap } from 'lucide-react';

const DEMO_PRESETS = [
  { label: 'Warehouse → Loading Bay', origin: 'Warehouse A', origin_x: 0, origin_y: 0, destination: 'Loading Bay 1', destination_x: 120, destination_y: 80, distance_km: 0.14 },
  { label: 'Receiving → Dispatch', origin: 'Receiving Dock', origin_x: -60, origin_y: 30, destination: 'Dispatch Zone', destination_x: 200, destination_y: 150, distance_km: 0.28 },
  { label: 'Cold Storage → Staging', origin: 'Cold Storage', origin_x: 50, origin_y: -40, destination: 'Staging Area B', destination_x: 180, destination_y: 100, distance_km: 0.19 },
];

interface TaskProposal { agent_id: string; available: boolean; capability_match: boolean; battery_pct: number; estimated_cost: number; utility: number; battery_score: number; capacity_score: number; workload_score: number; distance_score: number; priority_score: number; deadline_score: number; estimated_distance_km: number; reason: string; }
interface TaskRejection { agent_id: string; reason: string; }
interface NegotiationResponse { agent_id: string; selected_agent_id: string; compared_agent_ids: string[]; utility: number; accepted: boolean; reason: string; }
interface LogisticsTask { task_id: string; task_type: string; origin: string; destination: string; origin_location?: { x: number; y: number; z: number } | null; destination_location?: { x: number; y: number; z: number } | null; waypoints?: { x: number; y: number; z: number }[]; estimated_distance_km?: number | null; payload_weight: number; priority: number; required_capabilities: string[]; status: string; negotiation_status: string; assigned_agent_id: string | null; proposals: TaskProposal[]; rejections: TaskRejection[]; negotiation_responses: NegotiationResponse[]; created_at: string; parent_task_id?: string | null; is_parent?: boolean; subtask_ids?: string[]; subtask_type?: string | null; handoff_state?: string; handoff_from_agent_id?: string | null; handoff_reason?: string | null; plan_id?: string | null; reasoning_summary?: string | null; dependencies?: string[]; estimated_cost?: number | null; confidence?: number | null; fallback_status?: string | null; }
interface AgenticRun { task_id: string; phase: string; plan_summary: string; observation_summary: string; requested_action: string | null; replan_count: number; max_replans: number; replan_reason: string | null; final_outcome: string | null; observations: { observed_at: string; summary: string; task_status: string | null }[]; current_plan: { subtasks: { subtask_type: string; required_capabilities: string[] }[] } | null; }
interface RouteDecision { summary: string; selected_agent_id: string | null; route: { distance_km: number; estimated_travel_time_minutes: number; route_cost: number; explanation: string } | null; factors: string[]; }
interface MissionAnalytics { planning_time_seconds: number | null; negotiation_time_seconds: number | null; execution_time_seconds: number | null; total_duration_seconds: number; agents_involved: string[]; subtask_count: number; replans: number; handoffs: number; completion_state: string; }
interface EligibleAgent { agent_id: string; agent_type: string; status: string; battery_pct: number; active_task_id: string; last_seen_seconds_ago: number; }

const HEAL_STAGES = ['FAILURE DETECTED', 'RISK ASSESSMENT', 'REPLAN', 'REPLACEMENT', 'NEGOTIATION', 'HANDOFF', 'RESUMED'];

function HealingProgress({ replanCount, phase }: { replanCount: number; phase: string }) {
  const idx = replanCount > 0 ? Math.min(2 + replanCount, 6) : phase === 'REPLAN' ? 2 : 1;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {HEAL_STAGES.map((s, i) => (
        <span key={s} className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${i < idx ? 'bg-emerald-950 text-emerald-300' : i === idx ? 'bg-amber-950 text-amber-200 ring-1 ring-amber-500' : 'bg-slate-900 text-slate-600'}`}>{s}</span>
      ))}
    </div>
  );
}

export const TaskDashboard: React.FC<{ roleToken?: string }> = ({ roleToken = '' }) => {
  const [tasks, setTasks] = useState<LogisticsTask[]>([]);
  const [agenticRuns, setAgenticRuns] = useState<AgenticRun[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedRouteDecision, setSelectedRouteDecision] = useState<RouteDecision | null>(null);
  const [selectedMissionAnalytics, setSelectedMissionAnalytics] = useState<MissionAnalytics | null>(null);
  const [selectedTab, setSelectedTab] = useState<'overview' | 'agentic' | 'subtasks' | 'negotiation' | 'proposals' | 'events'>('overview');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eligibleAgents, setEligibleAgents] = useState<EligibleAgent[]>([]);
  const [failingAgentId, setFailingAgentId] = useState<string | null>(null);
  const [failResult, setFailResult] = useState<{ agentId: string; taskId: string; replanCount: number; phase: string } | null>(null);
  const [selectedPreset, setSelectedPreset] = useState(-1);
  const formRef = useRef<HTMLFormElement>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const [taskResp, agResp, eligResp] = await Promise.all([fetch('/api/v1/tasks'), fetch('/api/v1/agentic/tasks'), fetch('/api/v1/demo/eligible-failure-agents')]);
      if (!taskResp.ok) throw new Error(`HTTP ${taskResp.status}`);
      setTasks(await taskResp.json());
      if (agResp.ok) setAgenticRuns(await agResp.json());
      if (eligResp.ok) setEligibleAgents(await eligResp.json());
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed to load tasks'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchTasks(); const id = setInterval(fetchTasks, 3000); return () => clearInterval(id); }, [fetchTasks]);

  useEffect(() => {
    if (!failResult) return;
    const run = agenticRuns.find(r => r.task_id === failResult.taskId);
    if (run && (run.replan_count !== failResult.replanCount || run.phase !== failResult.phase)) {
      setFailResult(prev => prev ? { ...prev, replanCount: run.replan_count, phase: run.phase } : null);
    }
  }, [agenticRuns, failResult]);

  const rootTasks = useMemo(() => {
    const byParent = new Map<string, LogisticsTask[]>();
    for (const t of tasks) { if (t.parent_task_id) { const l = byParent.get(t.parent_task_id) || []; l.push(t); byParent.set(t.parent_task_id, l); } }
    return tasks.filter(t => !t.parent_task_id).map(task => ({ task, subtasks: (byParent.get(task.task_id) || []).sort((a, b) => a.task_id.localeCompare(b.task_id)) }));
  }, [tasks]);

  const applyPreset = (idx: number) => {
    setSelectedPreset(idx);
    const p = DEMO_PRESETS[idx];
    if (!formRef.current) return;
    const f = formRef.current;
    const set = (n: string, v: string) => { const el = f.elements.namedItem(n) as HTMLInputElement; if (el) el.value = v; };
    set('origin', p.origin); set('destination', p.destination);
    set('origin_x', String(p.origin_x)); set('origin_y', String(p.origin_y));
    set('destination_x', String(p.destination_x)); set('destination_y', String(p.destination_y));
    set('estimated_distance_km', String(p.distance_km));
    const det = f.querySelector('details'); if (det) det.open = true;
  };

  const createTask = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSubmitting(true); setError(null);
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    const cooperative = form.get('cooperative') === 'on';
    const agentic = form.get('agentic') === 'on';
    const rf = (n: string) => String(form.get(n) || '').trim();
    const coordsProvided = ['origin_x', 'origin_y', 'destination_x', 'destination_y'].every(n => rf(n) !== '');
    const waypoints = rf('waypoints').split(';').map(p => p.trim()).filter(Boolean).map(p => { const [x, y] = p.split(',').map(Number); return { x, y, z: 0 }; });
    const distText = rf('estimated_distance_km');
    try {
      const resp = await fetch(agentic ? '/api/v1/agentic/tasks' : '/api/v1/tasks', {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(roleToken ? { Authorization: `Bearer ${roleToken}` } : {}) },
        body: JSON.stringify({ task_type: cooperative || agentic ? 'cooperative_delivery' : form.get('task_type'), origin: form.get('origin'), destination: form.get('destination'), payload_weight: Number(form.get('payload_weight')), priority: Number(form.get('priority')), required_capabilities: cooperative || agentic ? [] : String(form.get('required_capabilities') || '').split(',').map(s => s.trim()).filter(Boolean), cooperative: cooperative || agentic, estimated_distance_km: distText ? Number(distText) : undefined, origin_location: coordsProvided ? { x: Number(form.get('origin_x')), y: Number(form.get('origin_y')), z: 0 } : undefined, destination_location: coordsProvided ? { x: Number(form.get('destination_x')), y: Number(form.get('destination_y')), z: 0 } : undefined, waypoints }),
      });
      if (!resp.ok) { const d = await resp.json(); throw new Error(d.detail || `HTTP ${resp.status}`); }
      const created: LogisticsTask = await resp.json();
      setSelectedTaskId(created.task_id); setSelectedTab(agentic ? 'agentic' : 'overview');
      setSelectedPreset(-1); formEl.reset(); await fetchTasks();
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed to create task'); }
    finally { setSubmitting(false); }
  };

  const simulateFailure = async (agentId: string) => {
    setFailingAgentId(agentId); setFailResult(null); setError(null);
    try {
      const resp = await fetch(`/api/v1/demo/agents/${encodeURIComponent(agentId)}/fail`, { method: 'POST' });
      if (!resp.ok) { const b = await resp.json(); throw new Error(b.detail || `HTTP ${resp.status}`); }
      const b = await resp.json();
      const trackId = b.affected_parent_task_id || b.affected_task_id;
      const run = agenticRuns.find(r => r.task_id === trackId);
      setFailResult({ agentId, taskId: trackId, replanCount: run?.replan_count ?? 0, phase: run?.phase ?? 'OBSERVE_RESULT' });
      await fetchTasks();
    } catch (err) { setError(err instanceof Error ? err.message : 'Simulation failed'); }
    finally { setFailingAgentId(null); }
  };

  const sc = (s: string) => s === 'ASSIGNED' || s === 'COMPLETED' || s === 'IN_PROGRESS' ? 'text-emerald-300 border-emerald-700/60 bg-emerald-950/40' : s === 'FAILED' || s === 'CANCELLED' ? 'text-rose-300 border-rose-700/60 bg-rose-950/40' : 'text-amber-200 border-amber-700/60 bg-amber-950/40';

  const renderTaskDetails = (task: LogisticsTask) => (
    <div className="space-y-2 text-xs">
      <div className="grid gap-2 sm:grid-cols-3">
        <p><span className="text-slate-500">Assigned</span><br /><span className="text-slate-200">{task.assigned_agent_id || 'Not allocated'}</span></p>
        <p><span className="text-slate-500">Negotiation</span><br /><span className="text-slate-200">{(task.negotiation_status || 'NOT_STARTED').replace(/_/g, ' ')}</span></p>
        <p><span className="text-slate-500">Capabilities</span><br /><span className="text-slate-200">{task.required_capabilities.join(', ') || 'None'}</span></p>
      </div>
      {task.handoff_state && task.handoff_state !== 'NONE' && <p className="text-amber-200">Handoff {task.handoff_state.toLowerCase()}: {task.handoff_reason || 'No reason'}</p>}
      {task.proposals.map(p => <div key={p.agent_id} className="flex flex-wrap justify-between gap-2 border-t border-slate-800 pt-2"><span className="text-slate-300">{p.agent_id} · {p.reason}</span><span className="font-mono text-slate-400">utility {p.utility.toFixed(3)} · cost {p.estimated_cost.toFixed(2)}</span></div>)}
      {task.rejections.map(r => <p key={r.agent_id} className="text-rose-300">{r.agent_id}: {r.reason}</p>)}
    </div>
  );

  const selectedEntry = rootTasks.find(({ task }) => task.task_id === selectedTaskId) || rootTasks[0];
  const selectedTask = selectedEntry?.task;
  const selectedSubtasks = selectedEntry?.subtasks || [];
  const selectedRun = selectedTask ? agenticRuns.find(r => r.task_id === selectedTask.task_id) : undefined;

  useEffect(() => {
    if (!selectedTask) { setSelectedRouteDecision(null); setSelectedMissionAnalytics(null); return; }
    const id = selectedTask.task_id;
    fetch(`/api/v1/analytics/missions/${encodeURIComponent(id)}`).then(r => r.ok ? r.json() as Promise<MissionAnalytics> : null).then(v => setSelectedMissionAnalytics(v));
    fetch('/api/v1/routes/optimize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task_type: selectedTask.task_type, origin: selectedTask.origin, destination: selectedTask.destination, origin_location: selectedTask.origin_location, destination_location: selectedTask.destination_location, waypoints: selectedTask.waypoints || [], estimated_distance_km: selectedTask.estimated_distance_km, payload_weight: selectedTask.payload_weight, priority: selectedTask.priority, required_capabilities: selectedTask.required_capabilities }) }).then(r => r.ok ? r.json() as Promise<RouteDecision> : null).then(setSelectedRouteDecision);
  }, [selectedTask?.task_id]);

  const activeEntries = rootTasks.filter(({ task }) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status));
  const historicalEntries = rootTasks.filter(({ task }) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status));
  const tabs = [{ id: 'overview', label: 'Overview' }, { id: 'agentic', label: 'Agentic AI' }, { id: 'subtasks', label: `Subtasks ${selectedSubtasks.length || ''}`.trim() }, { id: 'negotiation', label: 'Negotiation' }, { id: 'proposals', label: 'Proposals' }, { id: 'events', label: 'Events' }] as const;

  const renderTaskRow = ({ task, subtasks }: typeof rootTasks[number]) => {
    const run = agenticRuns.find(r => r.task_id === task.task_id);
    const assigned = [...new Set(subtasks.map(s => s.assigned_agent_id).filter(Boolean))];
    const neg = subtasks.some(s => s.negotiation_status === 'AGREED') ? 'AGREED' : subtasks.some(s => ['COLLECTING_PROPOSALS', 'EVALUATING'].includes(s.negotiation_status)) ? 'IN PROGRESS' : task.negotiation_status.replace(/_/g, ' ');
    return (
      <button key={task.task_id} type="button" onClick={() => { setSelectedTaskId(task.task_id); setSelectedTab('overview'); }} className={`grid w-full grid-cols-2 gap-x-3 gap-y-1 border-b border-slate-800 px-3 py-2.5 text-left transition sm:grid-cols-[1.2fr_1.6fr_0.8fr_1.2fr_1fr] sm:items-center ${selectedTask?.task_id === task.task_id ? 'bg-cyan-950/30' : 'hover:bg-slate-900/80'}`}>
        <span className="truncate font-mono text-[10px] text-slate-300">{task.task_id}</span>
        <span className="col-span-2 truncate text-xs text-slate-400 sm:col-span-1">{task.origin} → {task.destination}</span>
        <span className={`w-fit rounded border px-1.5 py-0.5 text-[9px] font-semibold ${sc(task.status)}`}>{task.status}</span>
        <span className="truncate text-[10px] text-slate-500">{assigned.join(', ') || task.assigned_agent_id || 'Unassigned'}</span>
        <span className="truncate text-[10px] text-slate-500">{run ? `AI · ${run.phase.replace(/_/g, ' ')}` : neg}</span>
      </button>
    );
  };

  return (
    <section className="space-y-3" aria-labelledby="tasks-heading">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md border border-cyan-900/70 bg-cyan-950/40 text-cyan-300"><ClipboardList className="h-4 w-4" /></div>
          <div><h2 id="tasks-heading" className="text-sm font-semibold text-white">Mission Operations</h2><p className="text-[11px] text-slate-500">Create, assign, and monitor live work</p></div>
        </div>
        <button type="button" onClick={fetchTasks} aria-label="Refresh" className="rounded border border-slate-800 p-1.5 text-slate-400 hover:bg-slate-900 hover:text-cyan-200">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <form ref={formRef} onSubmit={createTask} className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-slate-500">Demo presets:</span>
          {DEMO_PRESETS.map((p, i) => (
            <button key={p.label} type="button" onClick={() => applyPreset(i)} className={`rounded border px-2 py-1 text-[9px] font-semibold transition ${selectedPreset === i ? 'border-cyan-700 bg-cyan-950/60 text-cyan-200' : 'border-slate-700 text-slate-400 hover:text-slate-200'}`}>{p.label}</button>
          ))}
          <span className="text-[9px] italic text-slate-600">Simulated coordinates — not real GPS</span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
          <label className="text-[10px] text-slate-500">Task type<select name="task_type" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" defaultValue="delivery"><option value="delivery">Delivery</option><option value="transport">Transport</option><option value="inspection">Inspection</option><option value="cooperative_delivery">Cooperative delivery</option></select></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Origin<input name="origin" required maxLength={120} placeholder="Warehouse A" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500 sm:col-span-2">Destination<input name="destination" required maxLength={120} placeholder="Loading Bay 2" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Weight (kg)<input name="payload_weight" type="number" min="0" step="0.1" defaultValue="1" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500 sm:col-span-3">Capabilities<input name="required_capabilities" placeholder="ground_transport" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" /></label>
          <label className="text-[10px] text-slate-500">Priority<select name="priority" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200" defaultValue="3">{[1,2,3,4,5].map(v=><option key={v} value={v}>{v}</option>)}</select></label>
          <details className="col-span-2 self-end sm:col-span-4">
            <summary className="cursor-pointer py-1 text-[10px] text-slate-500">Route coordinates (auto-filled by preset)</summary>
            <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-slate-800 p-2 sm:grid-cols-4">
              <label className="text-[9px] text-slate-600 sm:col-span-2">Distance (km)<input name="estimated_distance_km" type="number" min="0" step="any" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
              <label className="text-[9px] text-slate-600">Origin X (m)<input name="origin_x" type="number" step="any" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
              <label className="text-[9px] text-slate-600">Origin Y (m)<input name="origin_y" type="number" step="any" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
              <label className="text-[9px] text-slate-600">Destination X (m)<input name="destination_x" type="number" step="any" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
              <label className="text-[9px] text-slate-600">Destination Y (m)<input name="destination_y" type="number" step="any" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
              <label className="text-[9px] text-slate-600 sm:col-span-4">Waypoints (x,y; x,y)<input name="waypoints" placeholder="10,5; 15,12" className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-200" /></label>
            </div>
          </details>
          <div className="flex flex-wrap items-end gap-x-4 gap-y-1 sm:col-span-2">
            <label className="flex items-center gap-1.5 pb-1 text-[11px] text-slate-300"><input name="cooperative" type="checkbox" className="rounded border-slate-600 bg-slate-950" />Cooperative</label>
            <label className="flex items-center gap-1.5 pb-1 text-[11px] text-cyan-200"><input name="agentic" type="checkbox" className="rounded border-cyan-800 bg-slate-950" />Agentic workflow</label>
          </div>
          <div className="flex items-end sm:col-span-1">
            <button disabled={submitting} className="inline-flex w-full items-center justify-center gap-1.5 rounded bg-cyan-700 px-3 py-2 text-[10px] font-semibold text-white transition hover:bg-cyan-600 disabled:opacity-50">
              <Plus className="h-3.5 w-3.5" />{submitting ? 'CREATING...' : 'CREATE MISSION'}
            </button>
          </div>
        </div>
      </form>

      {error && <div role="alert" className="flex items-center gap-2 rounded-md border border-rose-900/70 bg-rose-950/30 p-2.5 text-xs text-rose-200"><XCircle className="h-4 w-4" />{error}</div>}

      {/* ── Self-Healing Demo Panel ────────────────────────────────────────── */}
      {(eligibleAgents.length > 0 || failResult) && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/10 p-3">
          <div className="mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
            <span className="text-xs font-semibold text-amber-200">Self-Healing Demo</span>
            <span className="text-[10px] text-slate-500">Force an agent offline mid-mission → triggers real replan + handoff</span>
          </div>
          {eligibleAgents.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {eligibleAgents.map(agent => (
                <button key={agent.agent_id} type="button" disabled={failingAgentId !== null} onClick={() => simulateFailure(agent.agent_id)}
                  className="inline-flex items-center gap-1.5 rounded border border-rose-800/60 bg-rose-950/30 px-2.5 py-1.5 text-[10px] font-semibold text-rose-200 transition hover:bg-rose-950/50 disabled:opacity-50">
                  <Zap className="h-3 w-3" />FAIL {agent.agent_id}
                  <span className="text-rose-400/60">({agent.agent_type})</span>
                </button>
              ))}
            </div>
          )}
          {failResult && (
            <div className="mt-2">
              <p className="text-[10px] text-rose-300">Agent <span className="font-mono">{failResult.agentId}</span> forced offline on <span className="font-mono">{failResult.taskId}</span>. Orchestrator detecting and replanning…</p>
              <HealingProgress replanCount={failResult.replanCount} phase={failResult.phase} />
              <p className="mt-1 text-[9px] text-slate-500">Phase: {failResult.phase.replace(/_/g, ' ')} · Replans: {failResult.replanCount} · Check Decision Intelligence → Self-healing activity</p>
            </div>
          )}
          {eligibleAgents.length === 0 && !failResult && <p className="text-[10px] text-slate-500">No agents currently hold an active task assignment.</p>}
        </div>
      )}

      {/* ── Task list + detail ─────────────────────────────────────────────── */}
      <div className="grid gap-3 lg:grid-cols-12">
        <section className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50 lg:col-span-5">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2.5"><h3 className="text-xs font-semibold text-slate-200">Active missions</h3><span className="text-[10px] text-slate-500">{activeEntries.length}</span></div>
          <div className="max-h-[380px] overflow-y-auto">
            {activeEntries.length ? activeEntries.map(renderTaskRow) : <div className="px-3 py-8 text-center text-xs text-slate-500"><Radio className="mx-auto mb-2 h-4 w-4" />No active missions</div>}
          </div>
          {historicalEntries.length > 0 && (
            <details className="border-t border-slate-800">
              <summary className="cursor-pointer px-3 py-2 text-[10px] text-slate-500">Completed / historical ({historicalEntries.length})</summary>
              <div className="max-h-48 overflow-y-auto">{historicalEntries.map(renderTaskRow)}</div>
            </details>
          )}
        </section>

        <section className="min-h-64 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/50 lg:col-span-7">
          {selectedTask ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-2.5">
                <div className="min-w-0"><h3 className="truncate font-mono text-xs text-slate-200">{selectedTask.task_id}</h3><p className="mt-0.5 truncate text-[10px] text-slate-500">{selectedTask.origin} → {selectedTask.destination}</p></div>
                <span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${sc(selectedTask.status)}`}>{selectedTask.status}</span>
              </div>
              <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-slate-800 px-2">
                {tabs.map(tab => <button key={tab.id} type="button" role="tab" aria-selected={selectedTab === tab.id} onClick={() => setSelectedTab(tab.id)} className={`shrink-0 border-b-2 px-2 py-2 text-[10px] ${selectedTab === tab.id ? 'border-cyan-400 text-cyan-200' : 'border-transparent text-slate-500 hover:text-slate-300'}`}>{tab.label}</button>)}
              </div>
              <div role="tabpanel" className="max-h-[520px] overflow-y-auto p-3">
                {selectedTab === 'overview' && (
                  <div className="grid gap-3 text-xs sm:grid-cols-2">
                    <div><p className="text-[10px] uppercase text-slate-500">Route</p><p className="mt-1 text-slate-200">{selectedTask.origin} → {selectedTask.destination}</p></div>
                    <div><p className="text-[10px] uppercase text-slate-500">Load / priority</p><p className="mt-1 text-slate-200">{selectedTask.payload_weight} kg · P{selectedTask.priority}</p></div>
                    <div><p className="text-[10px] uppercase text-slate-500">Assigned agents</p><p className="mt-1 text-slate-200">{selectedSubtasks.map(s => `${s.subtask_type || s.task_type}: ${s.assigned_agent_id || 'unassigned'}`).join(' · ') || selectedTask.assigned_agent_id || 'Unassigned'}</p></div>
                    <div><p className="text-[10px] uppercase text-slate-500">Negotiation</p><p className="mt-1 text-slate-200">{selectedSubtasks.map(s => s.negotiation_status.replace(/_/g, ' ')).filter(Boolean).join(' · ') || selectedTask.negotiation_status.replace(/_/g, ' ')}</p></div>
                    {selectedRouteDecision && <div className="sm:col-span-2"><p className="text-[10px] uppercase text-slate-500">Route decision</p><p className="mt-1 text-slate-200">{selectedRouteDecision.route ? `${selectedRouteDecision.route.distance_km.toFixed(2)} km · ${selectedRouteDecision.route.estimated_travel_time_minutes.toFixed(1)} min · cost ${selectedRouteDecision.route.route_cost.toFixed(2)}` : 'Provide coordinates to compute route'}</p><p className="mt-1 text-[10px] text-slate-500">{selectedRouteDecision.summary}</p></div>}
                    {selectedMissionAnalytics && <div className="sm:col-span-2"><p className="text-[10px] uppercase text-slate-500">Mission analytics</p><p className="mt-1 text-slate-300">{selectedMissionAnalytics.completion_state} · {selectedMissionAnalytics.subtask_count} subtasks · {selectedMissionAnalytics.agents_involved.length} agents · {selectedMissionAnalytics.total_duration_seconds.toFixed(1)}s · {selectedMissionAnalytics.replans} replans · {selectedMissionAnalytics.handoffs} handoffs</p></div>}
                    {selectedTask.handoff_state && selectedTask.handoff_state !== 'NONE' && <div className="sm:col-span-2"><p className="text-[10px] uppercase text-amber-400">Handoff</p><p className="mt-1 text-amber-200">{selectedTask.handoff_state} · {selectedTask.handoff_reason || 'No reason'}</p></div>}
                  </div>
                )}
                {selectedTab === 'agentic' && (selectedRun ? (
                  <div className="space-y-3">
                    <div className="rounded-md border border-cyan-900/60 bg-cyan-950/20 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-xs font-semibold text-cyan-100">Observe / Plan / Validate / Delegate</h4><span className="text-[10px] font-semibold text-cyan-200">{selectedRun.phase.replace(/_/g, ' ')}</span></div>
                      <div className="mt-3 grid grid-cols-5 gap-1">
                        {['OBSERVE', 'PLAN', 'VALIDATE', 'DELEGATE', 'RESULT'].map((stage, i) => {
                          const cur = selectedRun.phase === 'REPLAN' ? i === 1 : selectedRun.phase === 'EXECUTE' ? i === 3 : (selectedRun.phase === 'OBSERVE_RESULT' || selectedRun.phase === 'COMPLETE') ? i === 4 : selectedRun.phase === stage;
                          const passed = selectedRun.phase === 'COMPLETE' || (selectedRun.phase === 'OBSERVE_RESULT' && i < 4) || (selectedRun.phase === 'EXECUTE' && i < 3);
                          return <div key={`${stage}-${i}`} className={`border-t-2 pt-1 text-center text-[8px] font-semibold sm:text-[9px] ${cur ? 'border-cyan-300 text-cyan-100' : passed ? 'border-emerald-700 text-emerald-300' : 'border-slate-700 text-slate-600'}`}>{stage}</div>;
                        })}
                      </div>
                      <p className="mt-3 text-xs text-slate-300">{selectedRun.observation_summary || 'Awaiting observation'}</p>
                      <p className="mt-1 text-[10px] text-slate-500">Replans: {selectedRun.replan_count}/{selectedRun.max_replans}{selectedRun.replan_reason ? ` · ${selectedRun.replan_reason}` : ''}</p>
                      {selectedRun.final_outcome && <p className="mt-2 border-t border-cyan-900/60 pt-2 text-xs text-emerald-200">{selectedRun.final_outcome}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">{selectedRun.current_plan?.subtasks.map((step, i) => <span key={`${step.subtask_type}-${i}`} className="rounded border border-slate-800 px-2 py-1 text-[10px] text-slate-400">{step.subtask_type} · {step.required_capabilities.join(', ')}</span>)}</div>
                  </div>
                ) : <p className="text-xs text-slate-500">Agentic workflow not enabled for this task.</p>)}
                {selectedTab === 'subtasks' && (
                  <div className="space-y-1.5">
                    {selectedSubtasks.length ? selectedSubtasks.map(subtask => (
                      <details key={subtask.task_id} className="rounded border border-slate-800 bg-slate-950/40">
                        <summary className="grid cursor-pointer grid-cols-[1fr_1fr_auto] items-center gap-2 px-2.5 py-2 text-[10px]">
                          <span className="font-medium text-slate-200">{subtask.subtask_type || subtask.task_type}</span>
                          <span className="truncate text-slate-500">{subtask.assigned_agent_id || 'Unassigned'}</span>
                          <span className={subtask.status === 'COMPLETED' ? 'text-emerald-300' : subtask.status === 'FAILED' ? 'text-rose-300' : 'text-slate-400'}>{subtask.status}</span>
                        </summary>
                        <div className="border-t border-slate-800 px-2.5 py-2">{renderTaskDetails(subtask)}</div>
                      </details>
                    )) : <p className="text-xs text-slate-500">No subtasks for this task.</p>}
                  </div>
                )}
                {selectedTab === 'negotiation' && (
                  <div className="space-y-2">
                    {selectedSubtasks.map(subtask => (
                      <div key={subtask.task_id} className="border-b border-slate-800 py-2">
                        <div className="grid grid-cols-[1fr_1fr_auto] items-center gap-2 text-[10px]">
                          <span className="text-slate-300">{subtask.subtask_type || subtask.task_type}</span>
                          <span className="truncate text-slate-500">{subtask.assigned_agent_id || 'No assignment'}</span>
                          <span className="text-slate-400">{subtask.negotiation_status.replace(/_/g, ' ')}</span>
                        </div>
                        {subtask.proposals.map(p => (
                          <div key={p.agent_id} className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9px]">
                            <span className={p.capability_match ? 'text-emerald-300' : 'text-rose-300'}>{p.capability_match ? '✓' : '×'} CAPABILITY</span>
                            <span className={p.battery_pct >= 20 ? 'text-emerald-300' : 'text-rose-300'}>{p.battery_pct >= 20 ? '✓' : '×'} BATTERY</span>
                            <span className={p.available ? 'text-emerald-300' : 'text-rose-300'}>{p.available ? '✓' : '×'} AVAILABLE</span>
                            <span className="text-slate-500">→ {p.agent_id}</span>
                          </div>
                        ))}
                        {subtask.negotiation_status === 'AGREED' && <p className="mt-1 text-[9px] text-emerald-300">✓ AGREED</p>}
                      </div>
                    ))}
                    {selectedSubtasks.length === 0 && <p className="text-xs text-slate-500">{selectedTask.negotiation_status.replace(/_/g, ' ')}</p>}
                    {selectedSubtasks.flatMap(s => s.negotiation_responses.map(r => <p key={`${s.task_id}-${r.agent_id}`} className="text-[10px] text-slate-500">{r.agent_id} {r.accepted ? 'agreed' : 'ranked'} {r.selected_agent_id} · {r.reason}</p>))}
                  </div>
                )}
                {selectedTab === 'proposals' && (
                  <div className="space-y-2">
                    {selectedSubtasks.flatMap(st => st.proposals.map(p => (
                      <div key={`${st.task_id}-${p.agent_id}`} className="grid grid-cols-[1fr_auto] gap-2 border-b border-slate-800 py-2 text-[10px]">
                        <div><p className="text-slate-200">{p.agent_id} <span className="text-slate-500">· {st.subtask_type}</span></p><p className="mt-1 text-slate-500">{p.reason}</p></div>
                        <p className="font-mono text-slate-400">{p.utility.toFixed(3)} / {p.estimated_cost.toFixed(2)}</p>
                      </div>
                    )))}
                    {selectedSubtasks.every(s => s.proposals.length === 0) && <p className="text-xs text-slate-500">No proposals recorded.</p>}
                  </div>
                )}
                {selectedTab === 'events' && (
                  <div className="space-y-2">
                    {selectedRun?.observations.slice().reverse().map((obs, i) => <p key={`${obs.observed_at}-${i}`} className="border-l border-slate-700 pl-2 text-[10px] text-slate-400"><span className="text-slate-600">{new Date(obs.observed_at).toLocaleTimeString()}</span> · {obs.summary}</p>)}
                    <p className="border-l border-slate-700 pl-2 text-[10px] text-slate-400"><span className="text-slate-600">{new Date(selectedTask.created_at).toLocaleString()}</span> · Mission created</p>
                    {!selectedRun && <p className="text-[10px] text-slate-500">Only creation time available for this task.</p>}
                  </div>
                )}
              </div>
            </>
          ) : <div className="flex h-full min-h-64 items-center justify-center text-xs text-slate-500">Select a mission to inspect operations.</div>}
        </section>
      </div>
    </section>
  );
};
