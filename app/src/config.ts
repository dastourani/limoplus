/**
 * Server address. Set in app/.env (see .env.example) — never written in code.
 * When moving to the real server, only EXPO_PUBLIC_API_URL changes.
 */
const apiUrl = process.env.EXPO_PUBLIC_API_URL;

if (!apiUrl) {
  throw new Error('EXPO_PUBLIC_API_URL is not set. Copy app/.env.example to app/.env.');
}

export const config = {
  apiUrl: apiUrl.replace(/\/+$/, ''),
} as const;
