"use client";

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react';
import type { User } from '@/lib/auth';
import {
  getCurrentUser,
  login as authLogin,
  logout as authLogout,
  register as authRegister,
} from '@/lib/auth';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  register: (email: string, password: string, username?: string) => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Auth Provider Component
 * Manages authentication state and provides auth methods to the app
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // 사용자 정보 새로고침
  const refreshUser = useCallback(async () => {
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
    } catch (error) {
      console.error('Failed to refresh user:', error);
      setUser(null);
    }
  }, []);

  // 초기화 시 사용자 정보 로드
  useEffect(() => {
    const initAuth = async () => {
      try {
        const currentUser = await getCurrentUser();
        setUser(currentUser);
      } catch (error) {
        console.error('Failed to initialize auth:', error);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
  }, []);

  // 주기적 토큰 갱신 (사용자 활성 시에만)
  useEffect(() => {
    if (!user) return;

    let lastActivityTime = Date.now();

    // 사용자 활동 감지
    const activityEvents = ['mousedown', 'keydown', 'scroll', 'touchstart'];
    const updateActivity = () => {
      lastActivityTime = Date.now();
    };

    activityEvents.forEach((event) => {
      window.addEventListener(event, updateActivity, { passive: true });
    });

    // 12분마다 토큰 갱신 (Access Token 15분 만료 고려)
    const refreshInterval = setInterval(
      async () => {
        const inactiveTime = Date.now() - lastActivityTime;

        // 5분 이상 비활성이면 갱신하지 않음
        if (inactiveTime > 5 * 60 * 1000) {
          console.log('[Auth] User inactive, skipping token refresh');
          return;
        }

        try {
          const response = await fetch('/api/auth/refresh', { method: 'POST' });
          if (response.ok) {
            console.log('[Auth] Token refreshed proactively');
          } else {
            console.error('[Auth] Token refresh failed:', response.status);
          }
        } catch (error) {
          console.error('[Auth] Failed to refresh token:', error);
        }
      },
      12 * 60 * 1000
    ); // 12분

    return () => {
      clearInterval(refreshInterval);
      activityEvents.forEach((event) => {
        window.removeEventListener(event, updateActivity);
      });
    };
  }, [user]);

  const login = useCallback(
    async (email: string, password: string) => {
      try {
        const user = await authLogin(email, password);
        setUser(user);
      } catch (error) {
        console.error('Login failed:', error);
        throw error;
      }
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      await authLogout();
      setUser(null);
    } catch (error) {
      console.error('Logout failed:', error);
      // 로그아웃은 에러가 나도 사용자를 로그아웃 상태로 만듦
      setUser(null);
      throw error;
    }
  }, []);

  const register = useCallback(
    async (email: string, password: string, username?: string) => {
      try {
        await authRegister(email, password, username);
        // 회원가입 후 자동 로그인
        await login(email, password);
      } catch (error) {
        console.error('Registration failed:', error);
        throw error;
      }
    },
    [login]
  );

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: user !== null,
    login,
    logout,
    register,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Hook to use auth context
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
