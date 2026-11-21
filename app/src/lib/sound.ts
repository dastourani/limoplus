/**
 * Short sound effects for celebrations (synthesised drops, pops and ticks in assets/sounds). On by default; the
 * learner can turn them off in the profile. They follow the phone's silent switch and mix with other audio.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

type Name = 'drop' | 'pop' | 'tick' | 'unlock';
const FILES = {
  drop1: require('../../assets/sounds/drop1.wav'),
  drop2: require('../../assets/sounds/drop2.wav'),
  drop3: require('../../assets/sounds/drop3.wav'),
  pop: require('../../assets/sounds/pop.wav'),
  tick: require('../../assets/sounds/tick.wav'),
  unlock: require('../../assets/sounds/unlock.wav'),
};
const KEY = 'limo.sound';

let enabled = true;
let ready: Promise<void> | null = null;
type Player = { play: () => void; seekTo: (s: number) => Promise<void>; volume: number };
const players: Record<string, Player[]> = {};

function setup() {
  if (ready) return ready;
  ready = (async () => {
    try {
      enabled = (await AsyncStorage.getItem(KEY)) !== 'off';
      const audio = await import('expo-audio');
      await audio.setAudioModeAsync({ playsInSilentMode: false, interruptionMode: 'mixWithOthers' }).catch(() => undefined);
      for (const [name, file] of Object.entries(FILES)) {
        // Two players per sound so quick repeats (drops landing) can overlap.
        players[name] = [audio.createAudioPlayer(file) as unknown as Player, audio.createAudioPlayer(file) as unknown as Player];
      }
    } catch {
      // no audio on this device: celebrations stay silent
    }
  })();
  return ready;
}

let turn = 0;
let lastAt = 0;
export function play(name: Name, volume = 1) {
  if (!enabled) return;
  setup().then(() => {
    if (!enabled) return;
    const now = Date.now();
    if (name === 'drop' && now - lastAt < 70) return;
    if (name === 'drop') lastAt = now;
    const key = name === 'drop' ? `drop${1 + Math.floor(Math.random() * 3)}` : name;
    const list = players[key];
    if (!list) return;
    const p = list[turn++ % list.length];
    try {
      p.volume = volume;
      p.seekTo(0).catch(() => undefined);
      p.play();
    } catch {
      // ignore
    }
  });
}

/** A short buzz at the peak of a celebration (phones only). */
export function buzz(kind: 'light' | 'success' = 'light') {
  if (Platform.OS === 'web') return;
  if (kind === 'success') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
  else Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
}

export async function soundEnabled() {
  await setup();
  return enabled;
}

export async function setSoundEnabled(on: boolean) {
  enabled = on;
  await AsyncStorage.setItem(KEY, on ? 'on' : 'off').catch(() => undefined);
}

/** Load the sounds early (app start) so the first celebration is not silent. */
export function preloadSounds() {
  setup();
}
