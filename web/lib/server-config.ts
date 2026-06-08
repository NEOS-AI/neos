import "server-only";

const DEFAULT_BACKEND_URL = "http://localhost:8518";

export function getBackendUrl(): string {
  const value = process.env.BACKEND_URL?.trim();
  return value ? value.replace(/\/$/, "") : DEFAULT_BACKEND_URL;
}

export function getAuthSecret(): string | undefined {
  return process.env.AUTH_SECRET;
}

export function getGoogleOAuthConfig(): {
  clientId: string | undefined;
  clientSecret: string | undefined;
} {
  return {
    clientId: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
  };
}

export function getAiGatewayApiKey(): string | undefined {
  return process.env.AI_GATEWAY_API_KEY;
}
