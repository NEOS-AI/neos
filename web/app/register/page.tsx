"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/contexts/auth-context';
import LoginForm from '@/components/auth/LoginForm';

/**
 * Register Page
 * Redirects to home if already authenticated
 * Shows the LoginForm in registration mode
 */
export default function RegisterPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    // Redirect to home if already authenticated
    if (isAuthenticated && !isLoading) {
      router.push('/');
    }
  }, [isAuthenticated, isLoading, router]);

  // Show loading while checking auth status
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-claude-darker">
        <div className="text-claude-text">Loading...</div>
      </div>
    );
  }

  // Don't render register form if already authenticated (will redirect)
  if (isAuthenticated) {
    return null;
  }

  return <LoginForm initialMode="register" onSuccess={() => router.push('/')} />;
}
