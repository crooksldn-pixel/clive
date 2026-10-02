import { Pressable, StyleSheet, View } from 'react-native';
import type { BottomTabBarProps } from 'expo-router/tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useCart } from '@/state/cart';
import { colour, font, hairline } from '@/theme/tokens';
import { Mono } from './Type';

/**
 * Text tabs on a 1px rule — the website's header nav, moved to the thumb.
 * The live tab carries the purple bar. The bag shows its count in brackets,
 * as the header does: BAG (2).
 */
export function CrooksTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  const { cart } = useCart();
  const count = cart?.totalQuantity ?? 0;

  return (
    <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, 8) }]} accessibilityRole="tablist">
      {state.routes.map((route, i) => {
        const focused = state.index === i;
        const title = String(descriptors[route.key].options.title ?? route.name).toUpperCase();
        const label = route.name === 'bag' && count > 0 ? `${title} (${count})` : title;
        const onPress = () => {
          const e = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
          if (!focused && !e.defaultPrevented) navigation.navigate(route.name, route.params);
        };
        return (
          <Pressable
            key={route.key}
            onPress={onPress}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={route.name === 'bag' ? `Bag, ${count} ${count === 1 ? 'item' : 'items'}` : title}
            style={({ pressed }) => [s.tab, pressed && s.pressed]}
          >
            <View style={[s.rule, focused && s.ruleOn]} />
            <Mono style={[s.label, focused && s.labelOn]}>{label}</Mono>
          </Pressable>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: colour.ground,
    borderTopWidth: hairline,
    borderTopColor: colour.line,
  },
  tab: { flex: 1, minHeight: 52, alignItems: 'center', justifyContent: 'center' },
  pressed: { backgroundColor: colour.press },
  rule: { position: 'absolute', top: -1, left: 0, right: 0, height: 2, backgroundColor: 'transparent' },
  ruleOn: { backgroundColor: colour.purple },
  label: { fontFamily: font.mono, fontSize: 11, letterSpacing: 2.4, color: colour.dim },
  labelOn: { color: colour.text },
});
