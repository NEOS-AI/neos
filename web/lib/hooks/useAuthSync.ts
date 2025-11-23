"use client";

import { useEffect } from 'react';
import { useAuth } from '@/lib/contexts/auth-context';
import { useChatStore } from '@/lib/stores/chat-store';

/**
 * Hook to sync authentication state with chat store
 * Automatically updates the chat store when user logs in/out
 */
export function useAuthSync() {
  const { user, isAuthenticated } = useAuth();
  const setUserId = useChatStore((state) => state.setUserId);

  useEffect(() => {
    if (isAuthenticated && user) {
      // User logged in - update chat store with user ID
      setUserId(user.user_id);
    } else {
      // User logged out - revert to anonymous
      setUserId('anonymous');
    }
  }, [user, isAuthenticated, setUserId]);
}
