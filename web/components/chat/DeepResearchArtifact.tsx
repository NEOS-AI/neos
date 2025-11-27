import React from 'react';
import type { ResearchArtifact, PhaseInfo } from '@/lib/types';
import { Loader2, CheckCircle2, Circle, Clock } from 'lucide-react';

interface DeepResearchArtifactProps {
  artifact: ResearchArtifact;
}

export function DeepResearchArtifact({ artifact }: DeepResearchArtifactProps) {
  return (
    <div className="w-full border border-blue-500/30 bg-gradient-to-br from-blue-50/50 to-indigo-50/50 dark:from-blue-950/20 dark:to-indigo-950/20 rounded-lg p-4 space-y-4 my-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-blue-600 dark:text-blue-400" />
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Deep Research in Progress
          </h3>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            Phase {artifact.phaseNumber}/8: {artifact.currentPhase}
          </p>
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400">
            {Math.round(artifact.progressPercentage)}%
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">Complete</div>
        </div>
      </div>

      {/* Overall Progress Bar */}
      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
        <div
          className="bg-gradient-to-r from-blue-500 to-indigo-500 h-2 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${artifact.progressPercentage}%` }}
        />
      </div>

      {/* Current Activity */}
      {artifact.currentActivity && (
        <div className="flex items-center gap-2 px-3 py-2 bg-white/60 dark:bg-gray-900/40 rounded-md">
          {artifact.isThinking && (
            <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
          )}
          <span className="text-sm text-gray-700 dark:text-gray-300">
            {artifact.currentActivity}
          </span>
        </div>
      )}

      {/* Current Search Query */}
      {artifact.currentQuery && (
        <div className="bg-white/60 dark:bg-gray-900/40 rounded-md p-3 space-y-2">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Current Search</p>
          <p className="text-sm font-mono text-gray-800 dark:text-gray-200 truncate">
            {artifact.currentQuery}
          </p>
          {artifact.searchProgress > 0 && (
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1">
              <div
                className="bg-blue-400 h-1 rounded-full transition-all duration-300"
                style={{ width: `${artifact.searchProgress}%` }}
              />
            </div>
          )}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-3 gap-2">
        <StatCard label="Sources" value={artifact.totalSources} />
        <StatCard label="Queries" value={artifact.totalQueries} />
        <StatCard label="Phase" value={`${artifact.phaseNumber}/8`} />
      </div>

      {/* Phase Progress */}
      <div className="space-y-2">
        <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Research Phases</p>
        <div className="grid grid-cols-4 gap-2">
          {artifact.phases.map((phase) => (
            <PhaseIndicator key={phase.phaseNumber} phase={phase} />
          ))}
        </div>
      </div>

      {/* Timeline (Last 5 events) */}
      {artifact.timeline.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Recent Activity</p>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {artifact.timeline.slice(-5).reverse().map((event, idx) => (
              <div
                key={idx}
                className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-2 px-2 py-1 rounded bg-white/40 dark:bg-gray-900/20"
              >
                <span className="text-gray-400 dark:text-gray-500 tabular-nums">
                  {new Date(event.timestamp).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <span className="flex-1 truncate">{event.activity}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-white/60 dark:bg-gray-900/40 rounded-md p-2.5 text-center">
      <p className="text-xs text-gray-600 dark:text-gray-400 mb-0.5">{label}</p>
      <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}

function PhaseIndicator({ phase }: { phase: PhaseInfo }) {
  const getIcon = () => {
    switch (phase.status) {
      case "completed":
        return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />;
      case "in_progress":
        return <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />;
      default:
        return <Circle className="h-3.5 w-3.5 text-gray-300 dark:text-gray-600" />;
    }
  };

  const getBgColor = () => {
    switch (phase.status) {
      case "completed":
        return "bg-green-100 dark:bg-green-900/30 border-green-300 dark:border-green-700";
      case "in_progress":
        return "bg-blue-100 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700";
      default:
        return "bg-gray-50 dark:bg-gray-800/30 border-gray-200 dark:border-gray-700";
    }
  };

  return (
    <div
      className={`flex flex-col items-center justify-center p-2 rounded-md border ${getBgColor()} transition-all duration-300`}
      title={`${phase.phaseName}${phase.duration ? ` (${(phase.duration / 1000).toFixed(1)}s)` : ''}`}
    >
      {getIcon()}
      <span className="text-[10px] font-medium text-gray-700 dark:text-gray-300 mt-1 text-center leading-tight">
        {phase.phaseNumber}
      </span>
    </div>
  );
}
