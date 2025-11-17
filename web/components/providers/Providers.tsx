"use client";

import { ReactNode } from 'react';
import { AuthProvider } from '@/lib/contexts/auth-context';
import { useAuthSync } from '@/lib/hooks/useAuthSync';
import dynamic from 'next/dynamic';

// Dynamically import PerformanceMonitor (development only)
const PerformanceMonitor = dynamic(() => import('@/components/PerformanceMonitor'), {
  ssr: false,
});

/**
 * Auth sync component - syncs auth state with chat store
 */
function AuthSync() {
  useAuthSync();
  return null;
}

/**
 * Client-side providers wrapper
 * Wraps all client-side context providers
 */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <AuthSync />
      {children}
      <PerformanceMonitor />
    </AuthProvider>
  );
}
