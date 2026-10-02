import React, { useState, useEffect, useCallback } from 'react';
import { 
  Activity, 
  Database, 
  Server, 
  Radio, 
  RefreshCw, 
  AlertTriangle, 
  XCircle, 
  Cpu, 
  ShieldCheck, 
} from 'lucide-react';

interface ServiceHealth {
  status: 'connected' | 'degraded' | 'offline' | string;
  latency_ms?: number;
  message?: string;
  error?: string;
}

interface HealthResponse {
  status: 'healthy' | 'degraded' | 'down' | string;
  timestamp: string;
  services: {
    backend: ServiceHealth;
    postgres: ServiceHealth;
    redis: ServiceHealth;
    mqtt: ServiceHealth;
  };
}

export const HealthDashboard: React.FC = () => {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchTime, setLastFetchTime] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    try {
      // Try proxy or relative backend route first, fallback to direct port 8000
      let response: Response;
      try {
        response = await fetch('/api/v1/health');
      } catch {
        response = await fetch('http://localhost:8000/api/v1/health');
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const json: HealthResponse = await response.json();
      setData(json);
      setError(null);
      setLastFetchTime(new Date());
    } catch (err: any) {
      setError(err.message || 'Failed to connect to FastAPI Backend');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'connected':
      case 'healthy':
        return (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-emerald-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Connected
          </span>
        );
      case 'degraded':
        return (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-amber-300">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            Degraded
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-rose-300">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            Offline
          </span>
        );
    }
  };

  const getOverallStatusBanner = (status?: string) => {
    if (error || status === 'down') {
      return (
        <div className="flex items-center justify-between p-4 rounded-xl bg-rose-950/40 border border-rose-800/40 text-rose-200">
          <div className="flex items-center space-x-3">
            <XCircle className="w-6 h-6 text-rose-400 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-rose-100">Infrastructure Alert</h4>
              <p className="text-xs text-rose-300/80">
                {error ? error : 'One or more essential infrastructure services are unreachable.'}
              </p>
            </div>
          </div>
          <button
            onClick={fetchHealth}
            className="px-3 py-1.5 text-xs font-medium bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/30 rounded-lg transition"
          >
            Retry Connection
          </button>
        </div>
      );
    }

    if (status === 'degraded') {
      return (
        <div className="flex items-center space-x-3 p-4 rounded-xl bg-amber-950/40 border border-amber-800/40 text-amber-200">
          <AlertTriangle className="w-6 h-6 text-amber-400 flex-shrink-0" />
          <div>
            <h4 className="font-semibold text-amber-100">Partial System Degradation</h4>
            <p className="text-xs text-amber-300/80">
              Backend is online, but some database or messaging brokers are offline. Check Docker containers.
            </p>
          </div>
        </div>
      );
    }

    return (
      <div className="flex items-center space-x-3 p-4 rounded-xl bg-emerald-950/30 border border-emerald-800/30 text-emerald-200">
        <ShieldCheck className="w-6 h-6 text-emerald-400 flex-shrink-0" />
        <div>
          <h4 className="font-semibold text-emerald-100">All Infrastructure Systems Operational</h4>
          <p className="text-xs text-emerald-300/80">
            PostgreSQL, Redis, MQTT, and FastAPI Backend are fully responsive and latency-verified.
          </p>
        </div>
      </div>
    );
  };

  const servicesList = [
    {
      key: 'backend',
      name: 'Backend',
      icon: Server,
      desc: 'FastAPI',
      details: data?.services.backend
    },
    {
      key: 'postgres',
      name: 'Database',
      icon: Database,
      desc: 'PostgreSQL',
      details: data?.services.postgres
    },
    {
      key: 'redis',
      name: 'Redis',
      icon: Cpu,
      desc: 'Cache',
      details: data?.services.redis
    },
    {
      key: 'mqtt',
      name: 'MQTT',
      icon: Radio,
      desc: 'Mosquitto',
      details: data?.services.mqtt
    }
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/70" aria-label="Infrastructure">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-cyan-300" />
          <h2 className="text-xs font-semibold text-slate-200">Infrastructure</h2>
          {error && <span className="text-[10px] text-rose-300">Health check unavailable</span>}
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-[10px] text-slate-500 sm:inline">Updated {lastFetchTime?.toLocaleTimeString() || '—'}</span>
          <button type="button" onClick={fetchHealth} disabled={loading} aria-label="Refresh infrastructure status" className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-cyan-200 disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <details>
        <summary className="grid cursor-pointer grid-cols-2 gap-2 px-4 py-3 sm:grid-cols-4">
          {servicesList.map((service) => {
            const Icon = service.icon;
            const status = service.details?.status || 'offline';
            return (
              <div key={service.key} className="flex min-w-0 items-center gap-2">
                <Icon className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                <span className="truncate text-xs text-slate-300">{service.name}</span>
                {getStatusBadge(status)}
                <span className="hidden text-[10px] tabular-nums text-slate-500 md:inline">{service.details?.latency_ms != null ? `${service.details.latency_ms.toFixed(0)} ms` : '—'}</span>
              </div>
            );
          })}
        </summary>
        {(error || data?.status === 'degraded' || data?.status === 'down') && (
          <div className="border-t border-slate-800 p-3">
            {getOverallStatusBanner(data?.status)}
          </div>
        )}
        <div className="grid gap-2 border-t border-slate-800 p-3 sm:grid-cols-2">
          {servicesList.map((service) => (
            <div key={service.key} className="flex items-center justify-between gap-3 px-2 py-1 text-xs">
              <span className="text-slate-400">{service.name} <span className="text-slate-600">· {service.desc}</span></span>
              <span className="truncate text-right text-slate-500">{service.details?.error || service.details?.message || 'No service message'}</span>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
};
