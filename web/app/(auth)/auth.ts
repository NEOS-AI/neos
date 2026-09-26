import NextAuth, { type DefaultSession } from "next-auth";
import type { DefaultJWT } from "next-auth/jwt";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { mergeRefreshedTokens, resolveAccessTokenExpiry } from "@/lib/auth-tokens";
import { DUMMY_PASSWORD } from "@/lib/constants";
import { getBackendUrl, getGoogleOAuthConfig } from "@/lib/server-config";
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

/**
 * 백엔드 액세스 토큰 갱신 — **이것이 코드베이스의 유일한 갱신 경로다.**
 *
 * 백엔드 리프레시 토큰은 1회용이므로(`auth_service.py:209,226`) 갱신 경로가 둘이면
 * 같은 토큰을 경쟁 소비해 세션이 죽는다. 다른 곳(특히 `lib/backend-api.ts`)에서
 * `/api/v1/auth/refresh`를 직접 호출하지 말 것.
 * 자세한 내용은 `lib/auth-tokens.ts` 주석 참조.
 */
async function refreshAccessToken(token: any) {
  const backendUrl = getBackendUrl();

  try {
    if (!token.backendRefreshToken) throw new Error("No refresh token");

    const response = await fetch(`${backendUrl}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token.backendRefreshToken }),
    });

    if (!response.ok) throw new Error(`Token refresh failed: ${response.status}`);

    // 회전된 refresh_token을 반드시 보존한다 (1회용 토큰)
    return mergeRefreshedTokens(token, await response.json());
  } catch (error) {
    console.error("[Auth] Error refreshing access token:", error);
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

/**
 * BE 로그인/게스트/구글-OAuth 응답에서 토큰 관련 필드만 뽑는다.
 * `authorize()` 세 곳과 google `signIn` 콜백이 이 함수 하나를 공유한다 —
 * `expires_in`을 셋 중 하나라도 빼먹으면 그 경로만 하드코딩 15분으로 되돌아간다
 * (#7). TTL "계산"은 여기서 하지 않는다 — 원값을 그대로 옮길 뿐이고,
 * 실제 계산은 전부 `resolveAccessTokenExpiry`가 한다.
 */
export function extractBackendTokenFields(data: any) {
  return {
    backendAccessToken: data?.access_token,
    backendRefreshToken: data?.refresh_token,
    expiresIn: data?.expires_in,
  };
}

/**
 * `jwt` 콜백에서 `accessTokenExpires`를 결정하는 부분만 순수 함수로 뺐다 —
 * 콜백 자체는 NextAuth 내부 배선이라 직접 호출해 테스트하기 어렵다.
 *
 * TTL 계산은 전부 `resolveAccessTokenExpiry`(`lib/auth-tokens.ts`)에 위임한다.
 * 여기서 고르는 것은 "어느 값을 넣을지"뿐이다:
 * - 로그인/가입 시점(`user`가 있음): 방금 로그인한 `user.expiresIn` (BE `expires_in`)
 * - 세션 갱신 시점(`user`가 없음): 클라이언트가 실어 보낸 `session.expiresIn`
 *   (없으면 헬퍼가 기본 TTL로 폴백한다 — 이 분기는 BE 응답이 없으므로 그 값을
 *   신뢰하는 것이 아니라 폴백을 보장하는 것이 목적이다)
 *
 * 분기는 `params.user`의 truthiness만 본다. `trigger`를 받아 분기에 쓰는
 * 버전을 시도한 적이 있는데, 현재 두 호출부가 우연히 `user`와
 * `trigger: "update"`를 동시에 넘기지 않아서만 안전했다 -- 그 안전성은
 * 함수가 아니라 호출부 모양에 있었고, 제3의 호출부가 생기면 조용히
 * 깨질 수 있었다. `trigger`를 아예 받지 않으면 그 발산 자체가 불가능하다.
 */
export function computeAccessTokenExpiry(params: {
  user?: { expiresIn?: unknown } | null;
  session?: { expiresIn?: unknown } | null;
  now?: number;
}): number {
  const now = params.now ?? Date.now();
  if (params.user) {
    return resolveAccessTokenExpiry(params.user.expiresIn, now);
  }
  return resolveAccessTokenExpiry(params.session?.expiresIn, now);
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
    /** BE `expires_in`(초). 원값 그대로 실어 나른다 — 계산은 `computeAccessTokenExpiry`가 한다. */
    expiresIn?: unknown;
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
      clientId: getGoogleOAuthConfig().clientId!,
      clientSecret: getGoogleOAuthConfig().clientSecret!,
      authorization: {
        params: { prompt: "consent", access_type: "offline", response_type: "code" },
      },
    }),
    Credentials({
      credentials: {},
      async authorize({ email, password }: any) {
        const backendUrl = getBackendUrl();

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
            ...extractBackendTokenFields(data),
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
        const backendUrl = getBackendUrl();

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
            ...extractBackendTokenFields(data),
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
        const backendUrl = getBackendUrl();

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
          Object.assign(user, extractBackendTokenFields(data));
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
        token.accessTokenExpires = computeAccessTokenExpiry({ user });
        token.error = undefined;
      }

      if (trigger === "update" && session?.backendAccessToken) {
        token.backendAccessToken = session.backendAccessToken;
        token.accessTokenExpires = computeAccessTokenExpiry({ session });
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
