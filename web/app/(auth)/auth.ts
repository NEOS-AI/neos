import { compare } from "bcrypt-ts";
import NextAuth, { type DefaultSession } from "next-auth";
import type { DefaultJWT } from "next-auth/jwt";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import { DUMMY_PASSWORD } from "@/lib/constants";
import { createGuestUser, getUser } from "@/lib/db/queries";
import { authConfig } from "./auth.config";

export type UserType = "guest" | "regular";

declare module "next-auth" {
  interface Session extends DefaultSession {
    user: {
      id: string;
      type: UserType;
      backendUserId?: string;
    } & DefaultSession["user"];
    backendAccessToken?: string;
    backendRefreshToken?: string;
  }

  // biome-ignore lint/nursery/useConsistentTypeDefinitions: "Required"
  interface User {
    id?: string;
    email?: string | null;
    type: UserType;
    backendUserId?: string;
    backendAccessToken?: string;
    backendRefreshToken?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT extends DefaultJWT {
    id: string;
    type: UserType;
    backendUserId?: string;
    backendAccessToken?: string;
    backendRefreshToken?: string;
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

          return {
            id: data.user.user_id,
            email: data.user.email,
            name: data.user.username || data.user.name || data.user.email,
            image: data.user.profile_picture_url || data.user.image,
            type: "regular" as UserType,
            backendUserId: data.user.user_id,
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
          // 백엔드 토큰을 user 객체에 저장 (JWT callback에서 사용)
          user.backendAccessToken = data.access_token;
          user.backendRefreshToken = data.refresh_token;
          user.id = data.user.user_id;
          user.backendUserId = data.user.user_id;
          user.type = "regular";
        } catch (error) {
          console.error("Google OAuth error:", error);
          return false;
        }
      }

      return true;
    },
    jwt({ token, user, trigger, session }) {
      if (user) {
        token.id = user.id as string;
        token.type = user.type;
        token.backendUserId = user.backendUserId;
        token.backendAccessToken = user.backendAccessToken;
        token.backendRefreshToken = user.backendRefreshToken;
      }

      // 클라이언트에서 update() 호출 시 (예: 토큰 갱신)
      if (trigger === "update" && session?.backendAccessToken) {
        token.backendAccessToken = session.backendAccessToken;
      }

      return token;
    },
    session({ session, token }) {
      if (session.user) {
        session.user.id = token.id;
        session.user.type = token.type;
        session.user.backendUserId = token.backendUserId;
        session.backendAccessToken = token.backendAccessToken;
        session.backendRefreshToken = token.backendRefreshToken;
      }

      return session;
    },
  },
});
