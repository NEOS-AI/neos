"use client";

import { useState, useEffect } from 'react';
import { performanceMonitor } from '@/lib/performance';
import { Activity, X } from 'lucide-react';

/**
 * PerformanceMonitor Component
 * Development-only component to display performance metrics
 */
export default function PerformanceMonitor() {
  const [isOpen, setIsOpen] = useState(false);
  const [summary, setSummary] = useState<any[]>([]);

  useEffect(() => {
    if (!isOpen) return;

    // Update summary every 2 seconds
    const interval = setInterval(() => {
      const newSummary = performanceMonitor.getSummary();
      setSummary(newSummary);
    }, 2000);

    return () => clearInterval(interval);
  }, [isOpen]);

  // Only show in development
  if (process.env.NODE_ENV !== 'development') {
    return null;
  }

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-4 right-4 p-3 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg transition-colors z-50"
        title="Open Performance Monitor"
        aria-label="Open Performance Monitor"
      >
        <Activity className="w-5 h-5" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 w-96 bg-gray-900 border border-gray-700 rounded-lg shadow-2xl z-50 max-h-[600px] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Performance Monitor</h3>
        </div>
        <button
          onClick={() => setIsOpen(false)}
          className="p-1 hover:bg-gray-800 rounded transition-colors"
          aria-label="Close"
        >
          <X className="w-4 h-4 text-gray-400" />
        </button>
      </div>

      {/* Metrics List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {summary.length === 0 ? (
          <div className="text-sm text-gray-400 text-center py-8">
            No metrics recorded yet.
            <br />
            Interact with the app to see performance data.
          </div>
        ) : (
          summary
            .sort((a, b) => b.avg - a.avg) // Sort by slowest first
            .map((metric) => (
              <div
                key={metric.name}
                className="p-3 bg-gray-800 rounded border border-gray-700"
              >
                <div className="text-xs font-medium text-white mb-2 truncate" title={metric.name}>
                  {metric.name}
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-gray-400">Avg:</span>
                    <span className="ml-1 text-blue-400 font-mono">
                      {metric.avg.toFixed(2)}ms
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400">Count:</span>
                    <span className="ml-1 text-gray-300 font-mono">
                      {metric.count}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400">Min:</span>
                    <span className="ml-1 text-green-400 font-mono">
                      {metric.min.toFixed(2)}ms
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400">Max:</span>
                    <span className="ml-1 text-red-400 font-mono">
                      {metric.max.toFixed(2)}ms
                    </span>
                  </div>
                </div>
              </div>
            ))
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-700 flex justify-between items-center">
        <div className="text-xs text-gray-400">
          {summary.length} metric{summary.length !== 1 ? 's' : ''}
        </div>
        <button
          onClick={() => {
            performanceMonitor.clear();
            setSummary([]);
          }}
          className="text-xs px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded transition-colors"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
