import { betterAuth } from "better-auth";
import { Pool } from "pg";

export const auth = betterAuth({
  database: new Pool({
    connectionString: process.env.AUTH_DATABASE_URL,
    max: 5,
  }),
  socialProviders: {
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID || "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || "",
    },
  },
  session: { expiresIn: 60 * 60 * 8, updateAge: 60 * 60 },
  trustedOrigins: (process.env.AUTH_TRUSTED_ORIGINS || "").split(",").filter(Boolean),
  advanced: {
    cookiePrefix: "aura",
    useSecureCookies: process.env.AUTH_SECURE_COOKIES !== "0",
    database: { generateId: "uuid" },
  },
  rateLimit: {
    enabled: process.env.AUTH_RATE_LIMIT_ENABLED !== "0",
    window: Number(process.env.AUTH_RATE_LIMIT_WINDOW || 60),
    max: Number(process.env.AUTH_RATE_LIMIT_MAX || 20),
  },
});

export const authConfig = { auth };
