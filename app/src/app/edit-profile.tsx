import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints } from '../api/endpoints';
import { Text, TextInput } from '../components/Text';
import { Button, Header, Screen } from '../components/ui';
import { useAuth } from '../lib/auth';
import { colors, radius, rtl } from '../theme';

export default function EditProfile() {
  const { first } = useLocalSearchParams<{ first?: string }>();
  const { user, setUser } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [lastName, setLastName] = useState(user?.last_name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = () => (first ? router.replace('/home') : router.back());

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      setUser(await endpoints.updateMe({ first_name: firstName.trim(), last_name: lastName.trim() }));
      done();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'ذخیره ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Header title={first ? 'خوش آمدید!' : 'ویرایش نام'} />
      <View style={styles.page}>
        {!!first && <Text style={[styles.help, rtl]}>اسمتان را بگویید تا لیمو پلاس شما را با نام صدا کند.</Text>}
        <Text style={[styles.label, rtl]}>نام</Text>
        <TextInput value={firstName} onChangeText={setFirstName} style={styles.input} maxLength={60} />
        <Text style={[styles.label, rtl]}>نام خانوادگی</Text>
        <TextInput value={lastName} onChangeText={setLastName} style={styles.input} maxLength={60} />
        {!!error && <Text style={{ color: colors.redDark }}>{error}</Text>}
        <Button label={busy ? '…' : 'ذخیره'} onPress={save} disabled={busy || !firstName.trim()} />
        {!!first && <Button label="بعداً" variant="outline" onPress={done} />}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 10 },
  help: { fontSize: 14, color: colors.muted, lineHeight: 24 },
  label: { fontSize: 14, fontWeight: '800', color: colors.ink },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.md, padding: 14, fontSize: 16, textAlign: 'right', writingDirection: 'rtl' },
});
