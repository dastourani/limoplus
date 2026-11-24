/**
 * Channel-aware Expo configuration.
 *
 * - `EXPO_PUBLIC_APP_CHANNEL=official`: «لیموخوان», package `ir.limookhan.app`, scheme `limookhan://`, HTTPS-only (`usesCleartextTraffic: false`).
 * - `EXPO_PUBLIC_APP_CHANNEL=test` (or unset): «لیموخوان آزمایشی», package `ir.limookhan.app.test`, scheme `limookhan-test://`, `usesCleartextTraffic: true`.
 */
module.exports = ({ config }) => {
  const explicit = process.env.EXPO_PUBLIC_APP_CHANNEL;
  const isWebExport = process.argv.includes('web');
  const channel =
    explicit === 'official'
      ? 'official'
      : explicit === 'test'
        ? 'test'
        : isWebExport
          ? 'official'
          : 'test';
  const isOfficial = channel === 'official';

  const plugins = (config.plugins || []).map((entry) => {
    if (Array.isArray(entry) && entry[0] === 'expo-build-properties') {
      return [
        'expo-build-properties',
        {
          ...(entry[1] || {}),
          android: {
            ...((entry[1] && entry[1].android) || {}),
            usesCleartextTraffic: !isOfficial,
          },
        },
      ];
    }
    return entry;
  });

  return {
    ...config,
    name: isOfficial ? 'لیموخوان' : 'لیموخوان آزمایشی',
    scheme: isOfficial ? 'limookhan' : 'limookhan-test',
    ios: {
      ...(config.ios || {}),
      bundleIdentifier: isOfficial ? 'ir.limookhan.app' : 'ir.limookhan.app.test',
    },
    android: {
      ...(config.android || {}),
      package: isOfficial ? 'ir.limookhan.app' : 'ir.limookhan.app.test',
    },
    plugins,
  };
};
