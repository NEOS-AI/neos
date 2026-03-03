import type { UserType } from "@/app/(auth)/auth";

type Entitlements = {
  maxMessagesPerDay: number;
};

export const entitlementsByUserType: Record<UserType, Entitlements> = {
  /*
   * For users without an account
   */
  guest: {
    maxMessagesPerDay: 10,
  },

  /*
   * For users with an account
   */
  regular: {
    maxMessagesPerDay: 200,
  },

  /*
   * For users with a premium subscription
   */
  premium: {
    maxMessagesPerDay: 1000,
  },

  /*
   * For enterprise users
   */
  enterprise: {
    maxMessagesPerDay: 5000,
  },

  /*
   * For admin users
   */
  admin: {
    maxMessagesPerDay: Number.POSITIVE_INFINITY,
  },
};
