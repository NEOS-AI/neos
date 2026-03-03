import { compare } from "bcrypt-ts";
import NextAuth, { type DefaultSession } from "next-auth";
import type { DefaultJWT } from "next-auth/jwt";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { DUMMY_PASSWORD } from "@/lib/constants";
import { createGuestUser, getUser } from "@/lib/db/queries";
import { authConfig } from "./auth.config";

export type UserType = "guest" | "regular" | "premium" | "enterprise" | "admin";

/**
 * 백엔드 role 값을 FE UserType으로 매핑
 * BE roles: guest, user, premium, enterprise, admin
 */
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

/**
 * Access Token 갱신 함수
 * @param token JWT 토큰
 * @returns 갱신된 토큰 또는 에러가 포함된 토큰
 */
async function refreshAccessToken(token: any) {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

  try {
    if (!token.backendRefreshToken) {
      console.error("[Auth] No refresh token available in token object");
      throw new Error("No refresh token available");
    }

    console.log("[Auth] Attempting to refresh access token...");

    const response = await fetch(`${backendUrl}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token.backendRefreshToken }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[Auth] Token refresh failed: ${response.status}`, errorText);
      throw new Error(`Token refresh failed: ${response.status}`);
    }

    const refreshedTokens = await response.json();

    if (!refreshedTokens.access_token) {
      console.error("[Auth] No access_token in refresh response:", refreshedTokens);
      throw new Error("Invalid refresh response: missing access_token");
    }

    console.log("[Auth] Token refreshed successfully");

    return {
      ...token,
      backendAccessToken: refreshedTokens.access_token,
      backendRefreshToken: refreshedTokens.refresh_token ?? token.backendRefreshToken,
      accessTokenExpires: Date.now() + 15 * 60 * 1000, // 15분 후 만료
      error: undefined,
    };
  } catch (error) {
    console.error("[Auth] Error refreshing access token:", error);

    return {
      ...token,
      error: "RefreshTokenExpired",
    };
  }
}

declare module "next-auth" {
  interface Session extends DefaultSession {
    user: {
      id: string;
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
        params: {
          prompt: "consent",
          access_type: "offline",
          response_type: "code",
        },
      },
    }),
    Credentials({
      credentials: {},
      async authorize({ email, password }: any) {
        // 백엔드 API 호출
        const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

        try {
          const response = await fetch(`${backendUrl}/api/v1/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });

          if (!response.ok) {
            // Timing attack 방지
            await compare(password, DUMMY_PASSWORD);
            return null;
          }

          const data = await response.json();
          // data = { access_token, refresh_token, user: { user_id, email, username, ... } }

          // 로컬 DB에서 사용자 찾기 또는 생성
          let localUserId: string;
          try {
            const existingUsers = await getUser(data.user.email);
            if (existingUsers.length > 0) {
              localUserId = existingUsers[0].id;
            } else {
              // 로컬 DB에 사용자 생성 (UUID 자동 생성)
              const [newUser] = await createGuestUser(undefined, data.user.email);
              localUserId = newUser.id;
            }
          } catch (error) {
            console.warn("Failed to create/find local user:", error);
            // 임시 UUID 생성
            localUserId = crypto.randomUUID();
          }

          return {
            id: localUserId, // 로컬 DB UUID 사용
            email: data.user.email,
            name: data.user.username || data.user.name || data.user.email,
            image: data.user.profile_picture_url || data.user.image,
            type: mapBackendRole(data.user.role ?? "user"),
            backendUserId: data.user.user_id, // 백엔드 user_id 저장
            backendRole: data.user.role,
            subscriptionTier: data.user.subscription_tier,
            usageQuota: data.user.usage_quota,
            backendAccessToken: data.access_token,
            backendRefreshToken: data.refresh_token,
          };
        } catch (error) {
          console.error("Backend login failed:", error);
          // Timing attack 방지
          await compare(password, DUMMY_PASSWORD);
          return null;
        }
      },
    }),
    Credentials({
      id: "guest",
      credentials: {},
      async authorize() {
        // 백엔드 API 호출
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
          // data = { access_token, refresh_token, user: { user_id, email, username, role: "guest" } }

          // 로컬 DB에도 guest 사용자 생성 (UUID 자동 생성)
          // 백엔드 user_id와 로컬 DB id는 다름 (백엔드는 문자열, 로컬은 UUID)
          let localUserId: string;
          try {
            const [guestUser] = await createGuestUser(undefined, data.user.email);
            localUserId = guestUser.id;
          } catch (error) {
            // 로컬 DB 생성 실패 시에도 로그인은 성공 (백엔드 인증만으로 충분)
            console.warn("Failed to create local guest user:", error);
            // 임시 UUID 생성 (로컬 DB 작업 실패를 방지)
            localUserId = crypto.randomUUID();
          }

          return {
            id: localUserId, // 로컬 DB ID 사용
            email: data.user.email,
            name: data.user.username,
            type: "guest" as UserType,
            backendUserId: data.user.user_id, // 백엔드 user_id 저장
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
    async signIn({ user, account, profile }) {
      if (account?.provider === "google") {
        // 백엔드 Google OAuth 연동
        const backendUrl = process.env.BACKEND_URL || "http://localhost:8518";

        try {
          const response = await fetch(
            `${backendUrl}/api/v1/auth/oauth/google`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                id_token: account.id_token,
              }),
            }
          );

          if (!response.ok) {
            console.error(
              "Google OAuth backend failed:",
              await response.text()
            );
            return false;
          }

          const data = await response.json();

          // 로컬 DB에서 사용자 찾기 또는 생성
          let localUserId: string;
          try {
            const existingUsers = await getUser(data.user.email);
            if (existingUsers.length > 0) {
              localUserId = existingUsers[0].id;
            } else {
              // 로컬 DB에 사용자 생성 (UUID 자동 생성)
              const [newUser] = await createGuestUser(undefined, data.user.email);
              localUserId = newUser.id;
            }
          } catch (error) {
            console.warn("Failed to create/find local user for Google OAuth:", error);
            // 임시 UUID 생성
            localUserId = crypto.randomUUID();
          }

          // 백엔드 토큰을 user 객체에 저장 (JWT callback에서 사용)
          user.backendAccessToken = data.access_token;
          user.backendRefreshToken = data.refresh_token;
          user.id = localUserId; // 로컬 DB UUID 사용
          user.backendUserId = data.user.user_id; // 백엔드 user_id 저장
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
      // 초기 로그인 시
      if (user) {
        console.log("[Auth JWT] Initial login - setting up token");
        token.id = user.id as string;
        token.type = user.type;
        token.backendUserId = user.backendUserId;
        token.backendRole = user.backendRole;
        token.subscriptionTier = user.subscriptionTier;
        token.usageQuota = user.usageQuota;
        token.backendAccessToken = user.backendAccessToken;
        token.backendRefreshToken = user.backendRefreshToken;
        token.accessTokenExpires = Date.now() + 15 * 60 * 1000; // 15분 후 만료
        token.error = undefined;
      }

      // 클라이언트에서 update() 호출 시 (예: 토큰 갱신)
      if (trigger === "update" && session?.backendAccessToken) {
        console.log("[Auth JWT] Manual token update triggered");
        token.backendAccessToken = session.backendAccessToken;
        token.accessTokenExpires = Date.now() + 15 * 60 * 1000;
      }

      // 토큰 만료 체크 및 자동 갱신
      if (token.accessTokenExpires && token.backendRefreshToken) {
        const timeUntilExpiry = token.accessTokenExpires - Date.now();
        const minutesUntilExpiry = Math.floor(timeUntilExpiry / 60000);

        // 만료 5분 전이면 아직 유효함
        if (timeUntilExpiry > 5 * 60 * 1000) {
          // console.log(`[Auth JWT] Token still valid (${minutesUntilExpiry} minutes remaining)`);
          return token;
        }

        // 만료 임박 또는 만료됨 - 갱신 시도
        console.log(`[Auth JWT] Token expiring soon (${minutesUntilExpiry} minutes), refreshing...`);
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

      // 토큰 갱신 에러를 세션에 전달
      session.error = token.error;

      return session;
    },
  },
});
