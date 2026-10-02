import React, { useEffect, useState } from 'react';
import { HealthDashboard } from './HealthDashboard';
import { RegistryDashboard } from './RegistryDashboard';
import { TaskDashboard } from './TaskDashboard';
import { FleetMap } from './FleetMap';
import { CheckCircle, XCircle, ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react';

type DashboardView = 'overview' | 'fleet' | 'missions' | 'map' | 'decisions' | 'analytics' | 'audit' | 'system';

interface FleetAgent {
  agent_id: string; agent_type: string; capabilities: string[]; payload_capacity_kg: number;
  status: string; last_seen: number; metadata: Record<string, unknown>;
  state: { battery_pct: number; status: string; is_available: boolean; current_task_id: string | null; location: { x: number; y: number; z: number } };
}
interface AgentHealthRecord {
  agent_id: string; health: string; battery_pct: number; status: string; available: boolean;
  connectivity_age_seconds: number; uptime_seconds: number; workload: number; failures: number;
  recent_errors: number; task_history: number; recommendations: string[];
}
interface Mission {
  task_id: string; parent_task_id: string | null; origin: string; destination: string;
  status: string; task_type: string; proposals: unknown[]; negotiation_responses: unknown[];
  origin_location?: { x: number; y: number; z: number } | null;
  destination_location?: { x: number; y: number; z: number } | null;
  waypoints?: { x: number; y: number; z: number }[];
}
interface AgenticRun {
  task_id: string; phase: string; observation_summary: string; plan_summary: string;
  requested_action: string | null; replan_count: number; replan_reason: string | null; final_outcome: string | null;
}
interface Risk { risk_id: string; severity: string; condition: string; agent_id: string | null; task_id: string | null; recommended_action: string; }
interface DispatchCandidate { agent_id: string; score: number; eligible: boolean; explanation: string; factors: Record<string, unknown>; }
interface Decision {
  decision_id: string; created_at: string; task_type: string; selected_agent_id: string | null;
  summary: string; factors: string[]; risk_count: number; mission_priority_score: number;
  mission_priority_summary: string; candidates: DispatchCandidate[];
  route?: { distance_km: number; estimated_travel_time_minutes: number; route_cost: number; provider: string; explanation: string } | null;
}
interface AuditEvent { event_id: string; timestamp: string; event_type: string; actor: string; agent_id: string | null; task_id: string | null; result: string; summary: string; }
interface HealingRecord {
  healing_id: string; detected_at: string; task_id: string; failed_subtask_id: string;
  failed_agent_id: string | null; failure: string; impact: string;
  replacement_candidates: string[]; selected_candidate: string | null; decision: string;
  handoff_result: string; recovery_status: string; recovered_at: string | null;
}
interface FleetAnalytics {
  total_agents: number; active_agents: number; offline_agents: number; utilization_pct: number;
  average_battery_pct: number; battery_buckets: Record<string, number>;
  active_missions: number; missions_completed: number; missions_failed: number;
  negotiations: number; handoffs: number; replans: number;
}
interface IntelligenceModule { name: string; status: string; }
interface OperationsDashboardProps { view: DashboardView; roleToken: string; onRoleTokenChange: (token: string) => void; }

async function fetchJson<T>(path: string, token?: string): Promise<T | null> {
  try {
    const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch { return null; }
}
const isActive = (a: FleetAgent) => { const now = Date.now() / 1000; return a.status !== 'OFFLINE' && a.status !== 'ERROR' && now - a.last_seen <= 15; };
const panel = 'rounded-lg border border-slate-800 bg-slate-900/60';
const sh = 'text-xs font-semibold uppercase tracking-wide text-slate-400';

function SeverityBadge({ s }: { s: string }) {
  if (s === 'CRITICAL') return <span className="rounded bg-rose-950/60 px-1.5 py-0.5 text-[9px] font-bold text-rose-300">CRITICAL</span>;
  if (s === 'WARNING') return <span className="rounded bg-amber-950/60 px-1.5 py-0.5 text-[9px] font-bold text-amber-300">WARNING</span>;
  return <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-bold text-slate-400">INFO</span>;
}

function FactorCheck({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] ${ok ? 'text-emerald-300' : 'text-slate-600 line-through'}`}>
      {ok ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3 text-slate-600" />}{label}
    </span>
  );
}

function HealingTimeline({ r }: { r: HealingRecord }) {
  const s = r.recovery_status;
  const stages = [
    { label: 'Failure',     done: true,                                      active: false,        failed: false },
    { label: 'Risk Assess', done: true,                                      active: false,        failed: false },
    { label: 'Replan',      done: s !== 'DETECTED',                          active: s === 'DETECTED', failed: false },
    { label: 'Replacement', done: ['NEGOTIATING','RECOVERED'].includes(s),   active: s === 'NEGOTIATING', failed: r.handoff_result === 'REJECTED' },
    { label: 'Handoff',     done: r.handoff_result === 'ACCEPTED' || s === 'RECOVERED', active: false, failed: r.handoff_result === 'REJECTED' },
    { label: 'Resumed',     done: s === 'RECOVERED',                         active: false,        failed: s === 'FAILED' },
  ];
  return (
    <div className="flex items-start gap-1 overflow-x-auto py-1">
      {stages.map((st, i) => (
        <React.Fragment key={st.label}>
          <div className="flex shrink-0 flex-col items-center gap-0.5">
            <div className={`flex h-5 w-5 items-center justify-center rounded-full text-[8px] font-bold
              ${st.failed ? 'bg-rose-900 text-rose-300' : st.done ? 'bg-emerald-900 text-emerald-300'
              : st.active ? 'bg-amber-900 text-amber-300 ring-1 ring-amber-400' : 'bg-slate-800 text-slate-600'}`}>
              {st.failed ? '✕' : st.done ? '✓' : i + 1}
            </div>
            <span className={`max-w-[48px] text-center text-[8px] leading-tight
              ${st.failed ? 'text-rose-400' : st.done ? 'text-emerald-400' : st.active ? 'text-amber-300' : 'text-slate-600'}`}>
              {st.label}
            </span>
          </div>
          {i < stages.length - 1 && <div className={`mt-2.5 h-px w-3 shrink-0 ${st.done && !st.failed ? 'bg-emerald-700' : 'bg-slate-700'}`} />}
        </React.Fragment>
      ))}
    </div>
  );
}

function DecisionCard({ d }: { d: Decision }) {
  const [exp, setExp] = useState(false);
  const num = d.decision_id.replace('DEC-', '#');
  const eligible = d.candidates.filter(c => c.eligible);
  const cf = eligible[0]?.factors as Record<string, unknown> | undefined;
  return (
    <div className="border-b border-slate-800 px-3 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[9px] text-slate-500">DECISION {num}</span>
            {d.selected_agent_id
              ? <span className="text-[11px] font-semibold text-slate-100"><span className="text-cyan-300">{d.selected_agent_id}</span> selected for {d.task_type}</span>
              : <span className="text-[11px] font-semibold text-amber-300">No eligible agent · {d.task_type}</span>}
          </div>
          <p className="mt-0.5 text-[10px] leading-snug text-slate-500">{d.summary}</p>
        </div>
        <button type="button" onClick={() => setExp(v => !v)} className="shrink-0 rounded p-0.5 text-slate-500 hover:text-slate-300">
          {exp ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>
      {cf && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/60 pt-2">
          <FactorCheck ok={Boolean(cf.capability_match)} label="Capability" />
          <FactorCheck ok={Boolean(cf.payload_capacity)} label="Payload" />
          <FactorCheck ok={(Number(cf.battery_pct) || 0) >= 20} label="Battery" />
          <FactorCheck ok={Boolean(cf.available)} label="Available" />
          <FactorCheck ok={Boolean(cf.deadline_feasible)} label="Deadline" />
          {cf.health !== undefined && <FactorCheck ok={cf.health !== 'CRITICAL'} label="Health" />}
        </div>
      )}
      {d.route && (
        <p className="mt-1.5 rounded bg-slate-950/50 px-2 py-1 text-[10px] text-slate-400">
          Route · {d.route.distance_km.toFixed(2)} km · {d.route.estimated_travel_time_minutes.toFixed(1)} min · cost {d.route.route_cost.toFixed(2)} · <span className="text-slate-600">{d.route.provider}</span>
        </p>
      )}
      <p className="mt-1 text-[9px] text-slate-600">{new Date(d.created_at).toLocaleString()} · priority {d.mission_priority_score.toFixed(2)} · {d.risk_count} risks</p>
      {exp && d.candidates.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-slate-800 pt-2">
          <p className="text-[9px] uppercase text-slate-600">All candidates ({d.candidates.length})</p>
          {d.candidates.slice(0, 8).map(c => (
            <div key={c.agent_id} className="flex justify-between text-[10px]">
              <span className={c.eligible ? 'text-slate-300' : 'text-slate-600'}>{c.agent_id}</span>
              <span className={c.eligible ? 'text-emerald-300' : 'text-rose-400/60'}>{c.eligible ? `score ${c.score.toFixed(2)}` : c.explanation}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function auditCategory(et: string): { label: string; color: string } {
  if (et === 'mission.created' || et === 'decision.dispatch') return { label: 'MISSION', color: 'text-cyan-300' };
  if (et === 'mission.replanned') return { label: 'REPLAN', color: 'text-amber-300' };
  if (et === 'mission.completed') return { label: 'COMPLETED', color: 'text-emerald-300' };
  if (et === 'mission.failed') return { label: 'FAILED', color: 'text-rose-300' };
  if (et.startsWith('handoff') || et.startsWith('self_healing.handoff')) return { label: 'HANDOFF', color: 'text-orange-300' };
  if (et.startsWith('self_healing')) return { label: 'HEALING', color: 'text-purple-300' };
  if (et.startsWith('assignment')) return { label: 'ASSIGN', color: 'text-emerald-300' };
  if (et.startsWith('agent.register') || et.startsWith('agent.capab') || et.startsWith('agent.activ') || et.startsWith('agent.deact') || et.startsWith('agent.arch')) return { label: 'REGISTRY', color: 'text-blue-300' };
  if (et.startsWith('security') || et.includes('identity_mismatch') || et.includes('authorization_denied')) return { label: 'SECURITY', color: 'text-rose-300' };
  if (et.startsWith('decision')) return { label: 'DECISION', color: 'text-cyan-400' };
  return { label: 'EVENT', color: 'text-slate-500' };
}

const AUDIT_FILTERS = [
  { value: '', label: 'All events' },
  { value: 'mission.created', label: 'Mission created' },
  { value: 'mission.completed', label: 'Mission completed' },
  { value: 'mission.replanned', label: 'Replans' },
  { value: 'self_healing.detected', label: 'Self-healing' },
  { value: 'handoff.accepted', label: 'Handoffs' },
  { value: 'agent.registered', label: 'Agent registration' },
  { value: 'decision.dispatch', label: 'Dispatch decisions' },
  { value: 'security.authorization_denied', label: 'Security events' },
];

export const OperationsDashboard: React.FC<OperationsDashboardProps> = ({ view, roleToken, onRoleTokenChange }) => {
  const [agents, setAgents] = useState<FleetAgent[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [agenticRuns, setAgenticRuns] = useState<AgenticRun[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [healing, setHealing] = useState<HealingRecord[]>([]);
  const [analytics, setAnalytics] = useState<FleetAnalytics | null>(null);
  const [agentHealth, setAgentHealth] = useState<AgentHealthRecord[]>([]);
  const [intelligenceModules, setIntelligenceModules] = useState<IntelligenceModule[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState('');

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      const [agentData, missionData, runData, riskData, analyticsData, healthData, intelligenceData] = await Promise.all([
        fetchJson<FleetAgent[]>('/api/v1/agents', roleToken),
        fetchJson<Mission[]>('/api/v1/tasks', roleToken),
        fetchJson<AgenticRun[]>('/api/v1/agentic/tasks', roleToken),
        fetchJson<Risk[]>('/api/v1/risks', roleToken),
        fetchJson<FleetAnalytics>('/api/v1/analytics/fleet', roleToken),
        fetchJson<AgentHealthRecord[]>('/api/v1/agents/health', roleToken),
        fetchJson<{ modules: IntelligenceModule[] }>('/api/v1/agentic/intelligence', roleToken),
      ]);
      if (!mounted) return;
      if (agentData) setAgents(agentData);
      if (missionData) setMissions(missionData);
      if (runData) setAgenticRuns(runData);
      if (riskData) setRisks(riskData);
      if (analyticsData) setAnalytics(analyticsData);
      if (healthData) setAgentHealth(healthData);
      if (intelligenceData) setIntelligenceModules(intelligenceData.modules);
      if (roleToken) {
        const [decisionData, eventData, healingData] = await Promise.all([
          fetchJson<Decision[]>('/api/v1/decisions/recent', roleToken),
          fetchJson<AuditEvent[]>(`/api/v1/audit?limit=200${auditFilter ? `&event_type=${encodeURIComponent(auditFilter)}` : ''}`, roleToken),
          fetchJson<HealingRecord[]>('/api/v1/self-healing', roleToken),
        ]);
        if (!mounted) return;
        if (decisionData) setDecisions(decisionData);
        if (eventData) setEvents(eventData);
        if (healingData) setHealing(healingData);
      } else {
        setDecisions([]); setEvents([]); setHealing([]);
      }
    };
    refresh();
    const id = window.setInterval(refresh, 5000);
    return () => { mounted = false; window.clearInterval(id); };
  }, [roleToken, auditFilter]);

  const fleet = agents.filter(isActive);
  const rootMissions = missions.filter(m => !m.parent_task_id);
  const activeMissions = rootMissions.filter(m => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(m.status));
  const criticalRisks = risks.filter(r => r.severity === 'CRITICAL');
  const selectedAgent = agents.find(a => a.agent_id === selectedAgentId);
  const selectedHealth = selectedAgent ? agentHealth.find(h => h.agent_id === selectedAgent.agent_id) : undefined;
  const selectedTask = missions.find(m => m.task_id === selectedAgent?.state.current_task_id);
  const runByTask = new Map(agenticRuns.map(r => [r.task_id, r]));
  const selectedRun = selectedAgent?.state.current_task_id ? runByTask.get(selectedAgent.state.current_task_id) : undefined;

  const mapEl = (large = false) => (
    <FleetMap agents={fleet} tasks={activeMissions} selectedAgentId={selectedAgentId}
      onSelectAgent={setSelectedAgentId} className={large ? 'h-[min(64vh,620px)]' : 'h-[320px]'} />
  );

  const riskRows = (items: Risk[]) => (
    <div className="divide-y divide-slate-800/60">
      {items.length ? items.slice(0, 10).map(r => (
        <div key={r.risk_id} className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 px-3 py-2 text-[10px] sm:grid-cols-[auto_1fr_1.4fr]">
          <SeverityBadge s={r.severity} />
          <span className="text-slate-200">{r.condition.replace(/_/g, ' ')}{r.agent_id ? ` · ${r.agent_id}` : ''}</span>
          <span className="col-span-2 text-slate-500 sm:col-span-1">{r.recommended_action}</span>
        </div>
      )) : <p className="px-3 py-5 text-center text-xs text-slate-500">No active operational risks.</p>}
    </div>
  );

  // ── SYSTEM ─────────────────────────────────────────────────────────────────
  if (view === 'system') {
    return (
      <div className="space-y-4">
        <div className={`${panel} p-4`}>
          <h2 className="text-sm font-semibold text-white">System access</h2>
          <p className="mt-1 text-xs text-slate-500">Tokens stay in this browser session only. Never stored or logged.</p>
          <label className="mt-3 block max-w-sm text-[10px] text-slate-400">
            Operator or admin bearer token
            <input type="password" autoComplete="off" value={roleToken} onChange={e => onRoleTokenChange(e.target.value)}
              placeholder="Enter configured role token"
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-slate-200 placeholder-slate-600" />
          </label>
          {roleToken && <p className="mt-2 text-[10px] text-emerald-400">Token active — protected views unlocked.</p>}
        </div>
        <HealthDashboard />
      </div>
    );
  }

  // ── FLEET ──────────────────────────────────────────────────────────────────
  if (view === 'fleet') {
    return (
      <div className="space-y-4">
        <RegistryDashboard roleToken={roleToken} />
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-slate-800 px-3 py-2.5"><h2 className={sh}>Agent health &amp; maintenance</h2></div>
          {agentHealth.length === 0
            ? <p className="px-3 py-5 text-xs text-slate-500">No health data — agents must be online and heartbeating.</p>
            : <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3">
              {agentHealth.map(h => (
                <div key={h.agent_id} className="rounded border border-slate-800 bg-slate-950/50 p-2.5">
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate text-[11px] font-semibold text-slate-200">{h.agent_id}</span>
                    <span className={`shrink-0 text-[10px] font-bold ${h.health === 'CRITICAL' ? 'text-rose-300' : h.health === 'WARNING' ? 'text-amber-300' : 'text-emerald-300'}`}>{h.health}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500">Battery {h.battery_pct.toFixed(0)}% · workload {h.workload} · failures {h.failures} · heartbeat {h.connectivity_age_seconds.toFixed(0)}s ago</p>
                  {h.recommendations.map(rec => <p key={rec} className="mt-1 text-[10px] text-amber-200">{rec}</p>)}
                </div>
              ))}
            </div>}
        </section>
        <section className={`${panel} p-3`}><h2 className={`${sh} mb-2`}>Fleet locations</h2>{mapEl(true)}</section>
      </div>
    );
  }

  // ── MISSIONS ───────────────────────────────────────────────────────────────
  if (view === 'missions') return <TaskDashboard roleToken={roleToken} />;

  // ── MAP ────────────────────────────────────────────────────────────────────
  if (view === 'map') {
    return (
      <div className="grid gap-3 lg:grid-cols-[1fr_280px]">
        <section className={`${panel} p-3`}>
          <div className="mb-2 flex items-center justify-between">
            <h2 className={sh}>Live fleet map</h2>
            <span className="text-[10px] text-slate-500">{fleet.length} active agent{fleet.length !== 1 ? 's' : ''}</span>
          </div>
          {mapEl(true)}
        </section>
        <aside className={`${panel} p-3`}>
          {selectedAgent ? (
            <>
              <div className="flex items-start justify-between gap-2">
                <div><h2 className="text-sm font-semibold text-white">{selectedAgent.agent_id}</h2><p className="text-[10px] uppercase text-slate-500">{selectedAgent.agent_type}</p></div>
                <span className={`text-[10px] font-bold ${selectedAgent.status === 'IDLE' ? 'text-emerald-300' : selectedAgent.status === 'BUSY' ? 'text-amber-300' : 'text-rose-300'}`}>{selectedAgent.status}</span>
              </div>
              <dl className="mt-3 space-y-2 text-[11px]">
                <div className="flex justify-between"><dt className="text-slate-500">Battery</dt><dd className="text-slate-200">{selectedAgent.state.battery_pct.toFixed(0)}%</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Available</dt><dd className="text-slate-200">{selectedAgent.state.is_available ? 'Yes' : 'No'}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Active mission</dt><dd className="max-w-[160px] truncate text-slate-200">{selectedAgent.state.current_task_id ?? 'None'}</dd></div>
                <div><dt className="text-slate-500">Local coord</dt><dd className="mt-0.5 font-mono text-slate-300">{selectedAgent.state.location.x}, {selectedAgent.state.location.y}, {selectedAgent.state.location.z}</dd></div>
                <div><dt className="text-slate-500">Capabilities</dt><dd className="mt-0.5 text-slate-300">{selectedAgent.capabilities.join(', ') || 'None advertised'}</dd></div>
                {selectedTask && <div><dt className="text-slate-500">Route</dt><dd className="mt-0.5 text-slate-300">{selectedTask.origin} → {selectedTask.destination}</dd></div>}
                {selectedRun && <div><dt className="text-slate-500">Agentic state</dt><dd className="mt-0.5 text-cyan-200">{selectedRun.phase.replace(/_/g, ' ')}</dd></div>}
                {selectedHealth && <div><dt className="text-slate-500">Health</dt><dd className={`mt-0.5 ${selectedHealth.health === 'CRITICAL' ? 'text-rose-300' : selectedHealth.health === 'WARNING' ? 'text-amber-300' : 'text-emerald-300'}`}>{selectedHealth.health} · {selectedHealth.workload} active tasks</dd></div>}
                {selectedHealth?.recommendations.map(rec => <div key={rec}><dt className="text-slate-500">Note</dt><dd className="mt-0.5 text-amber-200">{rec}</dd></div>)}
              </dl>
            </>
          ) : <p className="py-10 text-center text-xs text-slate-500">Click an agent marker to see live state.</p>}
        </aside>
      </div>
    );
  }

  // ── DECISION INTELLIGENCE ──────────────────────────────────────────────────
  if (view === 'decisions') {
    return (
      <div className="space-y-3">
        {!roleToken && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-900/60 bg-amber-950/20 px-3 py-2.5 text-xs text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
            Enter an operator or admin token in the SYSTEM tab to unlock decisions, self-healing records, and audit views.
          </div>
        )}
        <div className="grid gap-3 lg:grid-cols-2">
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-slate-800 px-3 py-2.5">
              <h2 className={sh}>Autonomous decisions</h2>
              <p className="mt-0.5 text-[10px] text-slate-600">Advisory dispatch · final allocation via decentralized MQTT negotiation</p>
            </div>
            {decisions.length
              ? decisions.slice(0, 10).map(d => <DecisionCard key={d.decision_id} d={d} />)
              : <p className="px-3 py-6 text-center text-xs text-slate-500">{roleToken ? 'No decisions yet — create a mission to trigger one.' : 'Operator token required.'}</p>}
          </section>
          <section className={`${panel} overflow-hidden`}>
            <div className="border-b border-slate-800 px-3 py-2.5">
              <h2 className={sh}>Self-healing activity</h2>
              <p className="mt-0.5 text-[10px] text-slate-600">Failure → replan → replacement → handoff → resumed</p>
            </div>
            {healing.length ? (
              <div className="divide-y divide-slate-800">
                {healing.slice(0, 8).map(r => (
                  <div key={r.healing_id} className="px-3 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[11px] font-semibold text-slate-200">{r.failed_subtask_id}</p>
                        <p className="truncate text-[10px] text-slate-500">{r.failure.replace(/_/g, ' ')}</p>
                      </div>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold
                        ${r.recovery_status === 'RECOVERED' ? 'bg-emerald-950/60 text-emerald-300'
                        : r.recovery_status === 'FAILED' ? 'bg-rose-950/60 text-rose-300'
                        : 'bg-amber-950/60 text-amber-300'}`}>{r.recovery_status}</span>
                    </div>
                    <HealingTimeline r={r} />
                    {r.selected_candidate && <p className="mt-1 text-[10px] text-cyan-300">Replacement: {r.selected_candidate}</p>}
                    {r.replacement_candidates.length > 0 && !r.selected_candidate && <p className="mt-1 text-[10px] text-slate-500">Candidates: {r.replacement_candidates.join(', ')}</p>}
                  </div>
                ))}
              </div>
            ) : <p className="px-3 py-6 text-center text-xs text-slate-500">{roleToken ? 'No self-healing events — trigger a mission with agent failure to test recovery.' : 'Operator token required.'}</p>}
          </section>
        </div>
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-slate-800 px-3 py-2.5">
            <h2 className={sh}>Live operational risks</h2>
            <p className="mt-0.5 text-[10px] text-slate-600">Active alerts only · stale historical agents excluded</p>
          </div>
          {riskRows(risks)}
        </section>
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-slate-800 px-3 py-2.5"><h2 className={sh}>Intelligence modules</h2></div>
          <div className="grid gap-px bg-slate-800 sm:grid-cols-5">
            {intelligenceModules.map(m => (
              <div key={m.name} className="bg-slate-950/70 px-3 py-2.5">
                <p className="text-[10px] font-medium leading-snug text-slate-300">{m.name}</p>
                <p className="mt-1 text-[9px] uppercase tracking-wide text-emerald-400">{m.status}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    );
  }

  // ── ANALYTICS ──────────────────────────────────────────────────────────────
  if (view === 'analytics') {
    const maxBucket = Math.max(1, ...Object.values(analytics?.battery_buckets ?? {}));
    const missionTotal = (analytics?.missions_completed ?? 0) + (analytics?.missions_failed ?? 0);
    const completedPct = missionTotal > 0 ? (analytics!.missions_completed / missionTotal) * 100 : 0;
    const failedPct    = missionTotal > 0 ? (analytics!.missions_failed    / missionTotal) * 100 : 0;
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-800 bg-slate-800 sm:grid-cols-4">
          {[['Total agents', analytics?.total_agents], ['Active agents', analytics?.active_agents], ['Active missions', analytics?.active_missions], ['Offline agents', analytics?.offline_agents]].map(([lbl, val]) => (
            <div key={String(lbl)} className="bg-slate-900 px-4 py-3">
              <p className="text-2xl font-semibold tabular-nums text-white">{val ?? '—'}</p>
              <p className="mt-1 text-[10px] uppercase tracking-wide text-slate-500">{lbl}</p>
            </div>
          ))}
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <section className={`${panel} p-4`}>
            <h2 className={`${sh} mb-3`}>Fleet performance</h2>
            <div className="space-y-3">
              {[{ label: 'Fleet utilization', value: analytics?.utilization_pct ?? 0, unit: '%' },
                { label: 'Average battery', value: analytics?.average_battery_pct ?? 0, unit: '%' }].map(({ label, value, unit }) => (
                <div key={label}>
                  <div className="mb-1 flex justify-between text-[10px]"><span className="text-slate-400">{label}</span><span className="font-mono text-slate-200">{value.toFixed(1)}{unit}</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                    <div className={`h-full rounded-full transition-all ${value > 80 ? 'bg-amber-500' : 'bg-cyan-500'}`} style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
                  </div>
                </div>
              ))}
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                {[{ label: 'Negotiations', value: analytics?.negotiations ?? 0, color: 'text-cyan-300' },
                  { label: 'Handoffs', value: analytics?.handoffs ?? 0, color: 'text-orange-300' },
                  { label: 'Replans', value: analytics?.replans ?? 0, color: 'text-amber-300' }].map(({ label, value, color }) => (
                  <div key={label} className="rounded border border-slate-800 bg-slate-950/50 py-2">
                    <p className={`text-xl font-semibold tabular-nums ${color}`}>{value}</p>
                    <p className="text-[9px] uppercase text-slate-600">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>
          <section className={`${panel} p-4`}>
            <h2 className={`${sh} mb-3`}>Mission outcomes</h2>
            <div className="space-y-3">
              {[{ label: 'Completed', value: analytics?.missions_completed ?? 0, pct: completedPct, color: 'bg-emerald-500', textColor: 'text-emerald-300' },
                { label: 'Failed',    value: analytics?.missions_failed    ?? 0, pct: failedPct,    color: 'bg-rose-500',    textColor: 'text-rose-300' }].map(({ label, value, pct, color, textColor }) => (
                <div key={label}>
                  <div className="mb-1 flex justify-between text-[10px]"><span className="text-slate-400">{label}</span><span className={`font-mono ${textColor}`}>{value}</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-800"><div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.max(pct > 0 ? 2 : 0, pct)}%` }} /></div>
                </div>
              ))}
              {missionTotal > 0 && <p className="text-[10px] text-slate-500">Success rate: <span className="font-mono text-emerald-300">{completedPct.toFixed(0)}%</span> of {missionTotal} missions</p>}
            </div>
            <h3 className={`${sh} mb-2 mt-4`}>Battery distribution</h3>
            <div className="flex items-end gap-2">
              {Object.entries(analytics?.battery_buckets ?? {}).map(([bucket, count]) => (
                <div key={bucket} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-[10px] font-mono text-slate-300">{count}</span>
                  <div className={`w-full rounded-t transition-all ${bucket.startsWith('0') ? 'bg-rose-700' : bucket.startsWith('20') ? 'bg-amber-600' : 'bg-cyan-700'}`}
                    style={{ height: `${Math.max(4, (count / maxBucket) * 64)}px` }} />
                  <span className="text-[9px] text-slate-600">{bucket}%</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    );
  }

  // ── AUDIT ──────────────────────────────────────────────────────────────────
  if (view === 'audit') {
    return (
      <section className={`${panel} overflow-hidden`}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-2.5">
          <div><h2 className={sh}>Audit trail</h2><p className="mt-0.5 text-[10px] text-slate-600">Structured lifecycle events · credentials and secrets excluded</p></div>
          <select value={auditFilter} onChange={e => setAuditFilter(e.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-300">
            {AUDIT_FILTERS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {!roleToken ? (
          <div className="flex items-center gap-2 px-4 py-6 text-xs text-amber-300"><AlertTriangle className="h-4 w-4 shrink-0" />Enter an operator token in SYSTEM to view the audit trail.</div>
        ) : events.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-slate-500">No matching audit events.</p>
        ) : (
          <div className="divide-y divide-slate-800/60">
            {events.map(ev => {
              const cat = auditCategory(ev.event_type);
              return (
                <div key={ev.event_id} className="grid gap-x-3 gap-y-0.5 px-3 py-2 text-[10px] sm:grid-cols-[130px_80px_1fr_120px]">
                  <span className="font-mono text-[9px] text-slate-600">{new Date(ev.timestamp).toLocaleString()}</span>
                  <span className={`font-semibold ${cat.color}`}>{cat.label}</span>
                  <span className="text-slate-300">{ev.summary}</span>
                  <span className="truncate text-right text-slate-500">{ev.agent_id ?? ev.task_id ?? ev.actor}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    );
  }

  // ── OVERVIEW ───────────────────────────────────────────────────────────────
  const recentMissions = [
    ...activeMissions,
    ...rootMissions.filter(m => ['COMPLETED','FAILED','CANCELLED'].includes(m.status)).slice(-4).reverse(),
  ];

  return (
    <div className="space-y-4">
      <section className={`${panel} overflow-hidden`}>
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2.5">
          <div><h2 className={sh}>Fleet status</h2><p className="mt-0.5 text-[10px] text-slate-600">{fleet.length} online · {agents.length - fleet.length} offline / historical</p></div>
          <span className="text-[10px] text-slate-500">Click agent on Live Map for details</span>
        </div>
        {fleet.length === 0
          ? <p className="px-3 py-5 text-center text-xs text-slate-500">No active agents. Add agents in the Fleet tab to get started.</p>
          : <div className="grid max-h-44 grid-cols-2 gap-px overflow-y-auto bg-slate-800 sm:grid-cols-3 lg:grid-cols-4">
            {fleet.map(a => (
              <button key={a.agent_id} type="button" onClick={() => setSelectedAgentId(a.agent_id)}
                className="flex min-w-0 items-center justify-between gap-2 bg-slate-950/70 px-2.5 py-2 text-left hover:bg-slate-900/80">
                <span className="min-w-0"><span className="block truncate text-[10px] font-semibold text-slate-200">{a.agent_id}</span><span className="block text-[9px] text-slate-600">{a.agent_type}</span></span>
                <span className="shrink-0 text-right"><span className={`block text-[9px] font-bold ${a.status === 'BUSY' ? 'text-amber-300' : 'text-emerald-300'}`}>{a.status}</span><span className="text-[9px] text-slate-600">{a.state.battery_pct.toFixed(0)}%</span></span>
              </button>
            ))}
          </div>}
      </section>

      <section className={`${panel} overflow-hidden`}>
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2.5">
          <h2 className={sh}>Active &amp; recent missions</h2>
          <span className="text-[10px] text-slate-600">{activeMissions.length} active</span>
        </div>
        <div className="divide-y divide-slate-800/60">
          {recentMissions.length ? recentMissions.map(m => {
            const run = runByTask.get(m.task_id);
            return (
              <div key={m.task_id} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 px-3 py-2 sm:grid-cols-[1fr_1.4fr_auto_1fr] sm:items-center">
                <span className="truncate font-mono text-[10px] text-slate-400">{m.task_id}</span>
                <span className="truncate text-xs text-slate-300">{m.origin} → {m.destination}</span>
                <span className={`text-[10px] font-semibold ${m.status === 'FAILED' ? 'text-rose-300' : m.status === 'COMPLETED' ? 'text-emerald-300' : 'text-amber-200'}`}>{m.status}</span>
                <span className="truncate text-[10px] text-slate-500">{run ? `${run.phase.replace(/_/g,' ')} · ${run.replan_count} replans` : m.task_type}</span>
              </div>
            );
          }) : <p className="px-3 py-5 text-center text-xs text-slate-500">No missions yet. Create one in the Missions tab.</p>}
        </div>
      </section>

      <section className={`${panel} p-3`}>
        <div className="mb-2 flex items-center justify-between">
          <h2 className={sh}>Live fleet map</h2>
          <span className="text-[10px] text-slate-500">{fleet.length} active agent{fleet.length !== 1 ? 's' : ''}</span>
        </div>
        {mapEl()}
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className={`${panel} overflow-hidden`}>
          <div className="border-b border-slate-800 px-3 py-2.5"><h2 className={sh}>Autonomous decisions</h2></div>
          {decisions.length
            ? decisions.slice(0, 4).map(d => <DecisionCard key={d.decision_id} d={d} />)
            : <p className="px-3 py-5 text-center text-xs text-slate-500">{roleToken ? 'No decisions yet.' : 'Enter operator token in SYSTEM to view.'}</p>}
        </section>
        <section className={`${panel} overflow-hidden`}>
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2.5">
            <h2 className={sh}>Operational risks</h2>
            {criticalRisks.length > 0 && <span className="rounded bg-rose-950/60 px-1.5 py-0.5 text-[9px] font-bold text-rose-300">{criticalRisks.length} CRITICAL</span>}
          </div>
          {riskRows(risks.slice(0, 6))}
        </section>
      </div>

      <section className={`${panel} overflow-hidden`}>
        <div className="border-b border-slate-800 px-3 py-2.5"><h2 className={sh}>Intelligence modules</h2></div>
        <div className="grid gap-px bg-slate-800 sm:grid-cols-5">
          {intelligenceModules.map(m => (
            <div key={m.name} className="bg-slate-950/70 px-3 py-2.5">
              <p className="text-[10px] font-medium leading-snug text-slate-300">{m.name}</p>
              <p className="mt-1 text-[9px] uppercase tracking-wide text-emerald-400">{m.status}</p>
            </div>
          ))}
          {intelligenceModules.length === 0 && <p className="col-span-5 px-3 py-4 text-xs text-slate-500">No intelligence modules loaded.</p>}
        </div>
      </section>
    </div>
  );
};
