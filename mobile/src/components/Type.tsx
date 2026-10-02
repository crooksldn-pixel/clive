import { StyleSheet, Text, type TextProps } from 'react-native';
import { colour, font } from '@/theme/tokens';

/** VT323 — titles, prices, the big buttons. */
export function Display({ style, ...p }: TextProps) {
  return <Text {...p} style={[s.display, style]} />;
}

/** Space Mono — everything functional. */
export function Mono({ style, ...p }: TextProps) {
  return <Text {...p} style={[s.mono, style]} />;
}

/** Small tracked uppercase label in the accent colour. */
export function Label({ style, ...p }: TextProps) {
  return <Text {...p} style={[s.label, style]} />;
}

/** Smallest tracked uppercase, dimmed. */
export function Micro({ style, ...p }: TextProps) {
  return <Text {...p} style={[s.micro, style]} />;
}

const s = StyleSheet.create({
  display: { fontFamily: font.display, color: colour.text, fontSize: 32, lineHeight: 32, textTransform: 'uppercase' },
  mono: { fontFamily: font.mono, color: colour.text, fontSize: 13, lineHeight: 20 },
  label: { fontFamily: font.mono, color: colour.accent, fontSize: 10, letterSpacing: 2.4, textTransform: 'uppercase' },
  micro: { fontFamily: font.mono, color: colour.dim, fontSize: 9, letterSpacing: 1.6, textTransform: 'uppercase' },
});
