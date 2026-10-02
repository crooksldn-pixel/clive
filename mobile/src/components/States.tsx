import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { colour, space } from '@/theme/tokens';
import { Button } from './Button';
import { Display, Micro, Mono } from './Type';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <View style={s.center} accessibilityRole="progressbar" accessibilityLabel={label}>
      <ActivityIndicator color={colour.accent} />
      <Micro style={s.gap}>{label}</Micro>
    </View>
  );
}

/** Says what went wrong in plain words and always offers the way out. */
export function Failed({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={s.center} accessibilityRole="alert">
      <Display style={s.title}>Not loaded</Display>
      <Mono style={s.body}>{message}</Mono>
      {onRetry ? <Button label="Try again" variant="ghost" onPress={onRetry} style={s.btn} /> : null}
    </View>
  );
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: { label: string; onPress: () => void } }) {
  return (
    <View style={s.center}>
      <Display style={s.title}>{title}</Display>
      {body ? <Mono style={s.body}>{body}</Mono> : null}
      {action ? <Button label={action.label} onPress={action.onPress} style={s.btn} /> : null}
    </View>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.xl },
  gap: { marginTop: space.md },
  title: { fontSize: 30, lineHeight: 30, textAlign: 'center' },
  body: { color: colour.dim, textAlign: 'center', marginTop: space.sm, maxWidth: 300 },
  btn: { marginTop: space.xl, alignSelf: 'center', maxWidth: 320, width: '100%' },
});
