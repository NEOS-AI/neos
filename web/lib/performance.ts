/**
 * Performance Monitoring Utilities
 * Provides tools for measuring and tracking application performance
 */

export interface PerformanceMetric {
  name: string;
  value: number;
  unit: string;
  timestamp: number;
}

/**
 * Performance logger for development
 */
class PerformanceMonitor {
  private metrics: PerformanceMetric[] = [];
  private timers: Map<string, number> = new Map();

  /**
   * Start a performance timer
   */
  start(name: string): void {
    this.timers.set(name, performance.now());
  }

  /**
   * End a performance timer and record the metric
   */
  end(name: string): number | null {
    const startTime = this.timers.get(name);
    if (!startTime) {
      console.warn(`[Performance] No start time found for: ${name}`);
      return null;
    }

    const duration = performance.now() - startTime;
    this.timers.delete(name);

    this.recordMetric({
      name,
      value: duration,
      unit: 'ms',
      timestamp: Date.now(),
    });

    return duration;
  }

  /**
   * Record a custom metric
   */
  recordMetric(metric: PerformanceMetric): void {
    this.metrics.push(metric);

    // Log in development
    if (process.env.NODE_ENV === 'development') {
      console.log(`[Performance] ${metric.name}: ${metric.value.toFixed(2)}${metric.unit}`);
    }

    // Keep only last 100 metrics to prevent memory leaks
    if (this.metrics.length > 100) {
      this.metrics.shift();
    }
  }

  /**
   * Get all recorded metrics
   */
  getMetrics(): PerformanceMetric[] {
    return [...this.metrics];
  }

  /**
   * Get metrics by name
   */
  getMetricsByName(name: string): PerformanceMetric[] {
    return this.metrics.filter(m => m.name === name);
  }

  /**
   * Get average value for a specific metric
   */
  getAverage(name: string): number | null {
    const metrics = this.getMetricsByName(name);
    if (metrics.length === 0) return null;

    const sum = metrics.reduce((acc, m) => acc + m.value, 0);
    return sum / metrics.length;
  }

  /**
   * Clear all metrics
   */
  clear(): void {
    this.metrics = [];
    this.timers.clear();
  }

  /**
   * Get performance summary
   */
  getSummary(): { name: string; avg: number; min: number; max: number; count: number }[] {
    const byName = new Map<string, number[]>();

    for (const metric of this.metrics) {
      if (!byName.has(metric.name)) {
        byName.set(metric.name, []);
      }
      byName.get(metric.name)!.push(metric.value);
    }

    const summary = [];
    for (const [name, values] of byName.entries()) {
      summary.push({
        name,
        avg: values.reduce((a, b) => a + b, 0) / values.length,
        min: Math.min(...values),
        max: Math.max(...values),
        count: values.length,
      });
    }

    return summary;
  }
}

// Export singleton instance
export const performanceMonitor = new PerformanceMonitor();

/**
 * Measure the performance of an async function
 */
export async function measureAsync<T>(
  name: string,
  fn: () => Promise<T>
): Promise<T> {
  performanceMonitor.start(name);
  try {
    const result = await fn();
    return result;
  } finally {
    performanceMonitor.end(name);
  }
}

/**
 * Measure the performance of a sync function
 */
export function measure<T>(name: string, fn: () => T): T {
  performanceMonitor.start(name);
  try {
    const result = fn();
    return result;
  } finally {
    performanceMonitor.end(name);
  }
}

/**
 * HOC to measure component render performance
 */
export function withPerformanceMonitoring<P extends object>(
  Component: React.ComponentType<P>,
  componentName: string
): React.ComponentType<P> {
  return function PerformanceMonitoredComponent(props: P) {
    const startTime = performance.now();

    React.useEffect(() => {
      const renderTime = performance.now() - startTime;
      performanceMonitor.recordMetric({
        name: `render:${componentName}`,
        value: renderTime,
        unit: 'ms',
        timestamp: Date.now(),
      });
    });

    return React.createElement(Component, props);
  };
}

/**
 * Hook to measure component render time
 */
export function usePerformanceMonitor(componentName: string) {
  const startTime = React.useRef(performance.now());

  React.useEffect(() => {
    const renderTime = performance.now() - startTime.current;
    performanceMonitor.recordMetric({
      name: `render:${componentName}`,
      value: renderTime,
      unit: 'ms',
      timestamp: Date.now(),
    });

    // Reset for next render
    startTime.current = performance.now();
  });
}

// Re-export React for the HOC and hook
import React from 'react';
