import { StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { Micro } from './Type';

/**
 * Stands in for a product with no photograph in Shopify, so the tile reads
 * as "no photo yet" rather than as a broken or still-loading image.
 */
export function NoImage({ size = 56 }: { size?: number }) {
  return (
    <View style={s.wrap} accessibilityLabel="No photo yet">
      <Image source={require('../../assets/mark.png')} style={[s.mark, { width: size, height: size * 0.66 }]} contentFit="contain" />
      <Micro>No photo yet</Micro>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10 },
  mark: { opacity: 0.25 },
});
