import { beforeEach, describe, expect, it, vi } from 'vitest';

const secureStore = new Map<string, string>();
let storedServerUrl: string | null = null;

vi.mock('react-native', () => ({
  Platform: { OS: 'android' },
}));

vi.mock('expo-device', () => ({
  supportedCpuArchitectures: ['arm64-v8a'],
}));

vi.mock('../storage', () => ({
  storage: {
    getServerUrl: vi.fn(async () => storedServerUrl),
    setServerUrl: vi.fn(async (val: string | null) => {
      storedServerUrl = val;
      if (val === null) secureStore.delete('serverUrl');
      else secureStore.set('serverUrl', val);
    }),
  },
}));

describe('dual Android channel config & HTTPS enforcement', () => {
  beforeEach(() => {
    storedServerUrl = null;
    secureStore.clear();
    vi.resetModules();
    delete process.env.EXPO_PUBLIC_APP_CHANNEL;
    delete process.env.EXPO_PUBLIC_API_URL;
  });

  it('produces distinct app.config.js identities, schemes, and cleartext flags for official vs test', async () => {
    const baseJson = await import('../../../app.json');
    const makeConfig = (await import('../../../app.config.js')).default;

    process.env.EXPO_PUBLIC_APP_CHANNEL = 'official';
    const official = makeConfig({ config: baseJson.expo });
    expect(official.name).toBe('لیموخوان');
    expect(official.scheme).toBe('limookhan');
    expect(official.android.package).toBe('ir.limookhan.app');
    const offBuildProps = official.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-build-properties')[1];
    expect(offBuildProps.android.usesCleartextTraffic).toBe(false);

    process.env.EXPO_PUBLIC_APP_CHANNEL = 'test';
    const testCfg = makeConfig({ config: baseJson.expo });
    expect(testCfg.name).toBe('لیموخوان آزمایشی');
    expect(testCfg.scheme).toBe('limookhan-test');
    expect(testCfg.android.package).toBe('ir.limookhan.app.test');
    const testBuildProps = testCfg.plugins.find((p: unknown) => Array.isArray(p) && p[0] === 'expo-build-properties')[1];
    expect(testBuildProps.android.usesCleartextTraffic).toBe(true);
  });

  it('enforces HTTPS in official builds both when saving and when reading legacy http:// overrides', async () => {
    process.env.EXPO_PUBLIC_APP_CHANNEL = 'official';
    process.env.EXPO_PUBLIC_API_URL = 'https://limookhan.ir';
    storedServerUrl = 'http://192.168.1.50:8000';

    const cfg = await import('../../config');
    expect(cfg.APP_CHANNEL).toBe('official');
    expect(cfg.APP_SCHEME).toBe('limookhan');

    // Reading an old stored http:// override discards it and falls back to https:// default.
    await expect(cfg.getApiUrl()).resolves.toBe('https://limookhan.ir');
    expect(storedServerUrl).toBeNull();

    // Saving an http:// URL is rejected; bare hosts get https://; valid https:// succeeds.
    expect(() => cfg.normalizeServerUrl('http://evil.example')).toThrow();
    await expect(cfg.setApiUrlOverride('http://192.168.1.50:8000')).rejects.toThrow();
    expect(cfg.normalizeServerUrl('api.limookhan.ir/')).toBe('https://api.limookhan.ir');
    await cfg.setApiUrlOverride('https://staging.limookhan.ir/');
    await expect(cfg.getApiUrl()).resolves.toBe('https://staging.limookhan.ir');
  });

  it('allows http:// overrides in test builds and uses limookhan-test scheme', async () => {
    process.env.EXPO_PUBLIC_APP_CHANNEL = 'test';
    process.env.EXPO_PUBLIC_API_URL = 'http://192.168.1.100:8000';

    const cfg = await import('../../config');
    expect(cfg.APP_CHANNEL).toBe('test');
    expect(cfg.APP_SCHEME).toBe('limookhan-test');
    await cfg.setApiUrlOverride('192.168.1.200:8000');
    await expect(cfg.getApiUrl()).resolves.toBe('http://192.168.1.200:8000');
  });
});
