/**
 * Basic authentication utilities
 * Provides simple session-based authentication using localStorage
 *
 * Note: This is a basic implementation for Week 1.
 * For production, integrate with a proper backend auth system (JWT, OAuth, etc.)
 */

export interface User {
  id: string;
  username: string;
  email?: string;
  createdAt: string;
}

export interface AuthSession {
  user: User;
  token: string;
  expiresAt: string;
}

const AUTH_STORAGE_KEY = 'neos_auth_session';
const SESSION_DURATION_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

/**
 * Check if a session is expired
 */
function isSessionExpired(session: AuthSession): boolean {
  return new Date(session.expiresAt) < new Date();
}

/**
 * Get current auth session from storage
 */
export function getSession(): AuthSession | null {
  if (typeof window === 'undefined') {
    return null; // SSR safety
  }

  try {
    const stored = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!stored) {
      return null;
    }

    const session: AuthSession = JSON.parse(stored);

    // Check if session is expired
    if (isSessionExpired(session)) {
      clearSession();
      return null;
    }

    return session;
  } catch (error) {
    console.error('Failed to get session:', error);
    clearSession();
    return null;
  }
}

/**
 * Save auth session to storage
 */
export function saveSession(user: User, token: string): void {
  if (typeof window === 'undefined') {
    return;
  }

  const expiresAt = new Date(Date.now() + SESSION_DURATION_MS).toISOString();

  const session: AuthSession = {
    user,
    token,
    expiresAt,
  };

  try {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
  } catch (error) {
    console.error('Failed to save session:', error);
  }
}

/**
 * Clear auth session from storage
 */
export function clearSession(): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch (error) {
    console.error('Failed to clear session:', error);
  }
}

/**
 * Get current user from session
 */
export function getCurrentUser(): User | null {
  const session = getSession();
  return session?.user || null;
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
  return getSession() !== null;
}

/**
 * Mock login function
 * In production, this would call a backend API
 *
 * @param username - Username or email
 * @param password - User password (not used in mock)
 */
export async function login(username: string, password: string): Promise<User> {
  // Simulate API delay
  await new Promise(resolve => setTimeout(resolve, 500));

  // Mock validation
  if (!username || username.trim().length === 0) {
    throw new Error('Username is required');
  }

  if (!password || password.length < 4) {
    throw new Error('Password must be at least 4 characters');
  }

  // Create mock user
  const user: User = {
    id: `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    username: username.trim(),
    email: username.includes('@') ? username : undefined,
    createdAt: new Date().toISOString(),
  };

  // Generate mock token
  const token = `mock_token_${btoa(username)}_${Date.now()}`;

  // Save session
  saveSession(user, token);

  return user;
}

/**
 * Logout user
 */
export async function logout(): Promise<void> {
  clearSession();

  // In production, would call backend to invalidate token
  await new Promise(resolve => setTimeout(resolve, 200));
}

/**
 * Register new user
 * Mock implementation for Week 1
 */
export async function register(
  username: string,
  email: string,
  password: string
): Promise<User> {
  // Simulate API delay
  await new Promise(resolve => setTimeout(resolve, 800));

  // Mock validation
  if (!username || username.trim().length < 3) {
    throw new Error('Username must be at least 3 characters');
  }

  if (!email || !email.includes('@')) {
    throw new Error('Valid email is required');
  }

  if (!password || password.length < 6) {
    throw new Error('Password must be at least 6 characters');
  }

  // Create mock user
  const user: User = {
    id: `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    username: username.trim(),
    email: email.trim(),
    createdAt: new Date().toISOString(),
  };

  // Generate mock token
  const token = `mock_token_${btoa(email)}_${Date.now()}`;

  // Save session
  saveSession(user, token);

  return user;
}

/**
 * Get auth headers for API requests
 */
export function getAuthHeaders(): Record<string, string> {
  const session = getSession();

  if (!session) {
    return {};
  }

  return {
    'Authorization': `Bearer ${session.token}`,
    'X-User-Id': session.user.id,
  };
}
