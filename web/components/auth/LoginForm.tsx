"use client";

import { useState, FormEvent } from 'react';
import { useAuth } from '@/lib/contexts/auth-context';
import { LogIn, UserPlus, AlertCircle } from 'lucide-react';

interface LoginFormProps {
  onSuccess?: () => void;
  initialMode?: 'login' | 'register';
}

export default function LoginForm({ onSuccess, initialMode = 'login' }: LoginFormProps) {
  const { login, register } = useAuth();
  const [isRegistering, setIsRegistering] = useState(initialMode === 'register');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form fields
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      if (isRegistering) {
        await register(email, password, username);
      } else {
        await login(email, password);
      }

      // Call success callback
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setIsLoading(false);
    }
  };

  const toggleMode = () => {
    setIsRegistering(!isRegistering);
    setError(null);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-claude-darker p-4">
      <div className="w-full max-w-md">
        {/* Logo & Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-4">
            <span className="text-2xl font-bold text-primary">N</span>
          </div>
          <h1 className="text-3xl font-bold text-claude-text mb-2">
            {isRegistering ? 'Create Account' : 'Welcome to NEOS'}
          </h1>
          <p className="text-claude-text-secondary">
            {isRegistering
              ? 'Sign up to start your AI journey'
              : 'Sign in to continue your conversations'}
          </p>
        </div>

        {/* Form */}
        <div className="bg-claude-dark border border-claude-border rounded-2xl p-6 shadow-xl">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-claude-text mb-2">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2.5 bg-claude-darker border border-claude-border rounded-lg text-claude-text placeholder-claude-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                placeholder="Enter your email"
                required
                disabled={isLoading}
              />
            </div>

            {/* Username (Register only) */}
            {isRegistering && (
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-claude-text mb-2">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-4 py-2.5 bg-claude-darker border border-claude-border rounded-lg text-claude-text placeholder-claude-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                  placeholder="Enter your username"
                  required
                  disabled={isLoading}
                />
              </div>
            )}

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-claude-text mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2.5 bg-claude-darker border border-claude-border rounded-lg text-claude-text placeholder-claude-text-secondary focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                placeholder={isRegistering ? 'Create a password (8-72 characters)' : 'Enter your password'}
                required
                disabled={isLoading}
                minLength={isRegistering ? 8 : 4}
                maxLength={72}
              />
            </div>

            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary hover:bg-primary-dark text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              {isLoading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>{isRegistering ? 'Creating Account...' : 'Signing In...'}</span>
                </>
              ) : (
                <>
                  {isRegistering ? <UserPlus className="w-4 h-4" /> : <LogIn className="w-4 h-4" />}
                  <span>{isRegistering ? 'Create Account' : 'Sign In'}</span>
                </>
              )}
            </button>
          </form>

          {/* Toggle Mode */}
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={toggleMode}
              disabled={isLoading}
              className="text-sm text-claude-text-secondary hover:text-primary transition-colors disabled:opacity-50"
            >
              {isRegistering ? (
                <>
                  Already have an account?{' '}
                  <span className="font-medium text-primary">Sign In</span>
                </>
              ) : (
                <>
                  Don&apos;t have an account?{' '}
                  <span className="font-medium text-primary">Create One</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
