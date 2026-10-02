import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colour, hairline, space } from '@/theme/tokens';
import { Display, Micro } from './Type';

/**
 * A tab's frame: the mark and wordmark on a 1px rule, as the website header.
 * `aside` sits at the right of the bar (a count, a status).
 */
export function Screen({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <SafeAreaView style={s.root} edges={['top', 'left', 'right']}>
      <View style={s.bar}>
        <View style={s.brand} accessible accessibilityRole="header" accessibilityLabel="CROOKSLDN">
          <Image source={require('../../assets/mark.png')} style={s.mark} contentFit="contain" />
          <Display style={s.word}>CROOKSLDN</Display>
        </View>
        {typeof aside === 'string' ? <Micro>{aside}</Micro> : aside}
      </View>
      <View style={s.body}>{children}</View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colour.ground },
  bar: {
    height: 48,
    paddingHorizontal: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: hairline,
    borderBottomColor: colour.line,
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  mark: { width: 30, height: 20 },
  word: { fontSize: 26, lineHeight: 26, letterSpacing: 1 },
  body: { flex: 1 },
});
