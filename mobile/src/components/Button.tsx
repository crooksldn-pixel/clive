import { ActivityIndicator, Pressable, StyleSheet, View, type ViewStyle } from 'react-native';
import { colour, font, TAP } from '@/theme/tokens';
import { Display, Mono } from './Type';

type Props = {
  label: string;
  onPress?: () => void;
  variant?: 'primary' | 'ghost';
  disabled?: boolean;
  busy?: boolean;
  /** The display face is for the one action that matters on a screen. */
  big?: boolean;
  style?: ViewStyle;
  accessibilityHint?: string;
};

/**
 * Primary is filled purple — reserved, as on the website, for the action the
 * screen exists for. A disabled primary drops to an outline rather than
 * dimming the fill, so "not yet" never looks like "broken".
 */
export function Button({ label, onPress, variant = 'primary', disabled, busy, big, style, accessibilityHint }: Props) {
  const inert = disabled || busy;
  const filled = variant === 'primary' && !inert;
  const Label = big ? Display : Mono;
  return (
    <Pressable
      onPress={inert ? undefined : onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!inert, busy: !!busy }}
      style={({ pressed }) => [
        s.base,
        big && s.big,
        filled ? s.filled : s.outline,
        pressed && !inert && (filled ? s.filledPressed : s.outlinePressed),
        style,
      ]}
    >
      <View style={s.row}>
        {busy ? <ActivityIndicator size="small" color={colour.dim} style={s.spin} /> : null}
        <Label
          style={[
            big ? s.bigText : s.text,
            { color: filled ? colour.onPurple : inert ? colour.dim : colour.text },
          ]}
          numberOfLines={1}
        >
          {label}
        </Label>
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  base: { minHeight: TAP + 4, paddingHorizontal: 16, justifyContent: 'center', alignItems: 'center', borderWidth: 1 },
  big: { minHeight: 58 },
  filled: { backgroundColor: colour.purple, borderColor: colour.purple },
  filledPressed: { borderColor: colour.accent },
  outline: { backgroundColor: 'transparent', borderColor: colour.line },
  outlinePressed: { backgroundColor: colour.press },
  row: { flexDirection: 'row', alignItems: 'center' },
  spin: { marginRight: 8 },
  text: { fontFamily: font.mono, fontSize: 11, letterSpacing: 2.6, textTransform: 'uppercase' },
  bigText: { fontFamily: font.display, fontSize: 24, lineHeight: 26, letterSpacing: 1 },
});
