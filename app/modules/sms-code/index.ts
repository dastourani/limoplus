import { requireOptionalNativeModule } from 'expo';

type SmsEvent = { message?: string; timeout?: boolean };
type SmsCodeNative = {
  getHash(): string | null;
  start(): Promise<boolean>;
  stop(): void;
  addListener(event: 'onSms', listener: (e: SmsEvent) => void): { remove(): void };
};

/** Android SMS Retriever; null where unavailable (web, iOS, or a build without the module). */
export const SmsCode = requireOptionalNativeModule<SmsCodeNative>('SmsCode');
