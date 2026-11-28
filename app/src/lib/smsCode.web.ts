/** Browsers read the code from the SMS themselves (autocomplete="one-time-code"); nothing to do here. */
export const smsAppHash = (): string | undefined => undefined;
export const listenForSmsCode = (_onCode: (code: string) => void) => () => undefined;
