import { Redirect } from 'expo-router';
import { useEffect, useState } from 'react';

import { Loading } from '../components/ui';
import { storage } from '../lib/storage';

/** First screen: go home if a major was chosen before, otherwise to the welcome screen. */
export default function Start() {
  const [target, setTarget] = useState<'/home' | '/welcome' | null>(null);
  useEffect(() => {
    storage.getMajor().then((major) => setTarget(major ? '/home' : '/welcome'));
  }, []);
  return target ? <Redirect href={target} /> : <Loading />;
}
