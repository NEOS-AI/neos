"use client";

import { ReactNode } from 'react';
import { AuthProvider } from '@/lib/contexts/auth-context';
import { useAuthSync } from '@/lib/hooks/useAuthSync';

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
    </AuthProvider>
  );
}
