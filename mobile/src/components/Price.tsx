import { StyleSheet, View, type TextStyle } from 'react-native';
import { formatMoney } from '@/lib/money';
import type { Money } from '@/lib/types';
import { colour } from '@/theme/tokens';
import { Display, Mono } from './Type';

type Props = { price: Money; compareAt?: Money | null; big?: boolean; style?: TextStyle };

/** Price, with the old price struck beside it only when there really is one. */
export function Price({ price, compareAt, big, style }: Props) {
  const Face = big ? Display : Mono;
  const now = formatMoney(price);
  const was = compareAt ? formatMoney(compareAt) : '';
  return (
    <View style={s.row} accessible accessibilityLabel={was ? `${now}, was ${was}` : now}>
      <Face style={[big ? s.big : s.small, style]}>{now}</Face>
      {was ? <Mono style={[s.was, big && s.wasBig]}>{was}</Mono> : null}
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  big: { fontSize: 30, lineHeight: 30 },
  small: { fontSize: 12, lineHeight: 18 },
  was: { color: colour.dim, fontSize: 11, textDecorationLine: 'line-through' },
  wasBig: { fontSize: 13 },
});
