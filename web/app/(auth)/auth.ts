import NextAuth, { type DefaultSession } from "next-auth";
import type { DefaultJWT } from "next-auth/jwt";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { DUMMY_PASSWORD } from "@/lib/constants";
import { compare } from "bcrypt-ts";
import { authConfig } from "./auth.config";

export type UserType = "guest" | "regular" | "premium" | "enterprise" | "admin";

function mapBackendRole(beRole: string): UserType {
  const roleMap: Record<string, UserType> = {
    guest: "guest",
    user: "regular",
    premium: "premium",
    enterprise: "enterprise",
    admin: "admin",
  };
  return roleMap[beRole] ?? "regular";
}

async function refreshAccessToken(token: any) {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

  try {
    if (!token.backendRefreshToken) throw new Error("No refresh token");

    const response = await fetch(`${backendUrl}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token.backendRefreshToken }),
    });

    if (!response.ok) throw new Error(`Token refresh failed: ${response.status}`);

    const refreshedTokens = await response.json();
    if (!refreshedTokens.access_token) throw new Error("Missing access_token");

    return {
      ...token,
      backendAccessToken: refreshedTokens.access_token,
      backendRefreshToken: refreshedTokens.refresh_token ?? token.backendRefreshToken,
      accessTokenExpires: Date.now() + 15 * 60 * 1000,
      error: undefined,
    };
  } catch (error) {
    console.error("[Auth] Error refreshing access token:", error);
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

declare module "next-auth" {
  interface Session extends DefaultSession {
    user: {
      id: string;           // = backendUserId (Phase 4 이후)
      type: UserType;
      backendUserId?: string;
      backendRole?: string;
      subscriptionTier?: string;
      usageQuota?: number;
    } & DefaultSession["user"];
    backendAccessToken?: string;
    backendRefreshToken?: string;
    error?: string;
  }

  // biome-ignore lint/nursery/useConsistentTypeDefinitions: "Required"
  interface User {
    id?: string;
    email?: string | null;
    type: UserType;
    backendUserId?: string;
    backendRole?: string;
    subscriptionTier?: string;
    usageQuota?: number;
    backendAccessToken?: string;
    backendRefreshToken?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT extends DefaultJWT {
    id: string;
    type: UserType;
    backendUserId?: string;
    backendRole?: string;
    subscriptionTier?: string;
    usageQuota?: number;
    backendAccessToken?: string;
    backendRefreshToken?: string;
    accessTokenExpires?: number;
    error?: string;
  }
}

export const {
  handlers: { GET, POST },
  auth,
  signIn,
  signOut,
} = NextAuth({
  ...authConfig,
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      authorization: {
        params: { prompt: "consent", access_type: "offline", response_type: "code" },
      },
    }),
    Credentials({
      credentials: {},
      async authorize({ email, password }: any) {
        const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

        try {
          const response = await fetch(`${backendUrl}/api/v1/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });

          if (!response.ok) {
            await compare(password, DUMMY_PASSWORD);
            return null;
          }

          const data = await response.json();

          return {
            id: data.user.user_id,       // BE user_id를 직접 사용
            email: data.user.email,
            name: data.user.username || data.user.name || data.user.email,
            image: data.user.profile_picture_url || data.user.image,
            type: mapBackendRole(data.user.role ?? "user"),
            backendUserId: data.user.user_id,
            backendRole: data.user.role,
            subscriptionTier: data.user.subscription_tier,
            usageQuota: data.user.usage_quota,
            backendAccessToken: data.access_token,
            backendRefreshToken: data.refresh_token,
          };
        } catch (error) {
          console.error("Backend login failed:", error);
          await compare(password, DUMMY_PASSWORD);
          return null;
        }
      },
    }),
    Credentials({
      id: "guest",
      credentials: {},
      async authorize() {
        const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

        try {
          const response = await fetch(`${backendUrl}/api/v1/auth/guest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });

          if (!response.ok) {
            console.error("Guest login failed:", await response.text());
            return null;
          }

          const data = await response.json();

          return {
            id: data.user.user_id,       // BE user_id를 직접 사용
            email: data.user.email,
            name: data.user.username,
            type: "guest" as UserType,
            backendUserId: data.user.user_id,
            backendAccessToken: data.access_token,
            backendRefreshToken: data.refresh_token,
          };
        } catch (error) {
          console.error("Backend guest login failed:", error);
          return null;
        }
      },
    }),
  ],
  callbacks: {
    async signIn({ user, account }) {
      if (account?.provider === "google") {
        const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

        try {
          const response = await fetch(`${backendUrl}/api/v1/auth/oauth/google`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id_token: account.id_token }),
          });

          if (!response.ok) {
            console.error("Google OAuth backend failed:", await response.text());
            return false;
          }

          const data = await response.json();

          user.id = data.user.user_id;   // BE user_id를 직접 사용
          user.backendUserId = data.user.user_id;
          user.backendAccessToken = data.access_token;
          user.backendRefreshToken = data.refresh_token;
          user.type = mapBackendRole(data.user.role ?? "user");
          user.backendRole = data.user.role;
          user.subscriptionTier = data.user.subscription_tier;
          user.usageQuota = data.user.usage_quota;
        } catch (error) {
          console.error("Google OAuth error:", error);
          return false;
        }
      }

      return true;
    },
    async jwt({ token, user, trigger, session }) {
      if (user) {
        token.id = user.id as string;
        token.type = user.type;
        token.backendUserId = user.backendUserId;
        token.backendRole = user.backendRole;
        token.subscriptionTier = user.subscriptionTier;
        token.usageQuota = user.usageQuota;
        token.backendAccessToken = user.backendAccessToken;
        token.backendRefreshToken = user.backendRefreshToken;
        token.accessTokenExpires = Date.now() + 15 * 60 * 1000;
        token.error = undefined;
      }

      if (trigger === "update" && session?.backendAccessToken) {
        token.backendAccessToken = session.backendAccessToken;
        token.accessTokenExpires = Date.now() + 15 * 60 * 1000;
      }

      if (token.accessTokenExpires && token.backendRefreshToken) {
        if (Date.now() + 5 * 60 * 1000 < token.accessTokenExpires) {
          return token;
        }
        return await refreshAccessToken(token);
      }

      return token;
    },
    session({ session, token }) {
      if (session.user) {
        session.user.id = token.id;
        session.user.type = token.type;
        session.user.backendUserId = token.backendUserId;
        session.user.backendRole = token.backendRole;
        session.user.subscriptionTier = token.subscriptionTier;
        session.user.usageQuota = token.usageQuota;
        session.backendAccessToken = token.backendAccessToken;
        session.backendRefreshToken = token.backendRefreshToken;
      }
      session.error = token.error;
      return session;
    },
  },
});
