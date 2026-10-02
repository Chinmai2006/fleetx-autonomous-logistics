import { useEffect, useState } from 'react';
import { OperationsDashboard } from './components/OperationsDashboard';
import { Activity, Bot, FileText } from 'lucide-react';

type DashboardView = 'overview' | 'fleet' | 'missions' | 'map' | 'decisions' | 'analytics' | 'audit' | 'system';

interface AgentSummary {
  status: string;
  last_seen: number;
}

interface TaskSummary {
  parent_task_id: string | null;
  status: string;
  proposals: unknown[];
  negotiation_responses: unknown[];
}

interface AgenticSummary {
  replan_count: number;
}

interface RiskSummary {
  risk_id: string;
}

interface OperationsSummary {
  activeAgents: number;
  activeTasks: number;
  completedTasks: number;
  negotiations: number;
  replans: number;
  alerts: number;
}

const emptySummary: OperationsSummary = {
  activeAgents: 0,
  activeTasks: 0,
  completedTasks: 0,
  negotiations: 0,
  replans: 0,
  alerts: 0,
};

export function App() {
  const [summary, setSummary] = useState(emptySummary);
  const [systemStatus, setSystemStatus] = useState<'healthy' | 'degraded' | 'down' | 'connecting'>('connecting');
  const [activeView, setActiveView] = useState<DashboardView>('overview');
  const [roleToken, setRoleToken] = useState('');

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      try {
        const [healthResponse, agentResponse, taskResponse, agenticResponse, riskResponse] = await Promise.all([
          fetch('/api/v1/health'),
          fetch('/api/v1/agents'),
          fetch('/api/v1/tasks'),
          fetch('/api/v1/agentic/tasks'),
          fetch('/api/v1/risks'),
        ]);
        if (![healthResponse, agentResponse, taskResponse, agenticResponse, riskResponse].every((response) => response.ok)) {
          throw new Error('Operations API unavailable');
        }
        const [health, agents, tasks, agenticRuns, risks] = await Promise.all([
          healthResponse.json(),
          agentResponse.json() as Promise<AgentSummary[]>,
          taskResponse.json() as Promise<TaskSummary[]>,
          agenticResponse.json() as Promise<AgenticSummary[]>,
          riskResponse.json() as Promise<RiskSummary[]>,
        ]);
        if (!mounted) return;
        const roots = tasks.filter((task) => !task.parent_task_id);
        const now = Date.now() / 1000;
        setSummary({
          activeAgents: agents.filter((agent) => agent.status !== 'OFFLINE' && agent.status !== 'ERROR' && now - agent.last_seen <= 15).length,
          activeTasks: roots.filter((task) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)).length,
          completedTasks: roots.filter((task) => task.status === 'COMPLETED').length,
          negotiations: tasks.filter((task) => task.proposals.length > 0 || task.negotiation_responses.length > 0).length,
          replans: agenticRuns.reduce((total, run) => total + run.replan_count, 0),
          alerts: risks.length,
        });
        setSystemStatus(health.status);
      } catch {
        if (mounted) setSystemStatus('down');
      }
    };
    refresh();
    const interval = window.setInterval(refresh, 5000);
    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, []);

  const kpis = [
    { label: 'Fleet online', value: summary.activeAgents },
    { label: 'Active missions', value: summary.activeTasks },
    { label: 'Alerts', value: summary.alerts },
    { label: 'Completed', value: summary.completedTasks },
    { label: 'Negotiations', value: summary.negotiations },
    { label: 'Replans', value: summary.replans },
  ];

  const navigation: { id: DashboardView; label: string }[] = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'fleet', label: 'FLEET' },
    { id: 'missions', label: 'MISSIONS' },
    { id: 'map', label: 'LIVE MAP' },
    { id: 'decisions', label: 'DECISION INTELLIGENCE' },
    { id: 'analytics', label: 'ANALYTICS' },
    { id: 'audit', label: 'AUDIT' },
    { id: 'system', label: 'SYSTEM' },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-950/95">
        <div className="mx-auto flex min-h-16 max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-cyan-900 bg-cyan-950/50 text-cyan-300">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold text-white sm:text-base">
                Decentralized Multi-Agent Coordination Platform
              </h1>
              <p className="text-[11px] text-slate-500">
                AUTONOMOUS LOGISTICS CONTROL TOWER
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-4">
            <div className={`flex items-center gap-2 text-[10px] font-semibold tracking-wide sm:text-xs ${systemStatus === 'healthy' ? 'text-emerald-300' : systemStatus === 'connecting' ? 'text-slate-400' : 'text-amber-300'}`}>
              <span className={`h-2 w-2 rounded-full ${systemStatus === 'healthy' ? 'bg-emerald-400' : systemStatus === 'connecting' ? 'bg-slate-500' : 'bg-amber-400'}`} />
              <span>{systemStatus === 'healthy' ? 'ALL SYSTEMS OPERATIONAL' : systemStatus === 'connecting' ? 'CONNECTING' : 'SYSTEM DEGRADED'}</span>
            </div>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-300 transition hover:border-cyan-800 hover:text-cyan-200"
            >
              <FileText className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Swagger API Docs</span>
            </a>
          </div>
        </div>
      </header>

      <nav aria-label="Main navigation" className="sticky top-16 z-40 border-b border-slate-800 bg-slate-950/95">
        <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 sm:px-6 lg:px-8">
          {navigation.map((item) => (
            <button key={item.id} type="button" onClick={() => setActiveView(item.id)} className={`shrink-0 border-b-2 px-3 py-3 text-[9px] font-semibold tracking-wide transition ${activeView === item.id ? 'border-cyan-400 text-cyan-200' : 'border-transparent text-slate-500 hover:text-slate-200'}`}>
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="mx-auto w-full max-w-7xl flex-1 space-y-6 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <section aria-label="Operations summary" className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-800 bg-slate-800 sm:grid-cols-3 lg:grid-cols-6">
          {kpis.map((kpi) => (
            <div key={kpi.label} className="min-h-20 bg-slate-900/90 px-4 py-3">
              <div className="text-2xl font-semibold tabular-nums text-white">{kpi.value}</div>
              <div className="mt-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">{kpi.label}</div>
            </div>
          ))}
        </section>
        <OperationsDashboard view={activeView} roleToken={roleToken} onRoleTokenChange={setRoleToken} />
      </main>

      <footer className="border-t border-slate-800 px-4 py-4 text-center text-[11px] text-slate-600">
        <span className="inline-flex items-center gap-2"><Activity className="h-3.5 w-3.5" /> Live fleet operations</span>
      </footer>
    </div>
  );
}

export default App;
