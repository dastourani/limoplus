import { SmsCode } from '../../modules/sms-code';

/** The app's hash for the SMS (Android only), or undefined. Sent with the code request so the server can add it. */
export function smsAppHash(): string | undefined {
  try {
    return SmsCode?.getHash() ?? undefined;
  } catch {
    return undefined;
  }
}

/** Listens for the login SMS for up to 5 minutes and passes the 6-digit code to onCode. Returns a stop function. */
export function listenForSmsCode(onCode: (code: string) => void): () => void {
  if (!SmsCode) return () => undefined;
  const sub = SmsCode.addListener('onSms', (e) => {
    const code = e.message?.match(/\b(\d{6})\b/)?.[1];
    if (code) onCode(code);
  });
  SmsCode.start().catch(() => undefined);
  return () => {
    sub.remove();
    try {
      SmsCode?.stop();
    } catch {
      // already stopped
    }
  };
}
