import { memo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { sized } from '@/lib/image';
import { formatMoney } from '@/lib/money';
import type { ProductCard } from '@/lib/types';
import { colour, font, hairline, space } from '@/theme/tokens';
import { NoImage } from './NoImage';
import { Micro, Mono } from './Type';
import { Price } from './Price';

type Props = { product: ProductCard; width: number; onPress: () => void };

/** One cell of the catalogue: picture, name, price. Sold out says so in words. */
export const ProductTile = memo(function ProductTile({ product, width, onPress }: Props) {
  const soldOut = !product.availableForSale;
  const price = formatMoney(product.price);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="link"
      accessibilityLabel={`${product.title}, ${price}${soldOut ? ', sold out' : ''}`}
      style={({ pressed }) => [s.cell, { width }, pressed && s.pressed]}
    >
      <View style={[s.frame, { height: Math.round(width * 1.25) }]}>
        {product.featuredImage ? (
          <Image
            source={{ uri: sized(product.featuredImage.url, width * 3) }}
            style={[s.img, soldOut && s.dimmed]}
            contentFit="contain"
            transition={150}
            recyclingKey={product.id}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <NoImage />
        )}
        {soldOut ? (
          <View style={s.flag}>
            <Micro style={s.flagText}>Sold out</Micro>
          </View>
        ) : null}
      </View>
      <View style={s.meta}>
        <Mono style={s.title} numberOfLines={2}>{product.title}</Mono>
        <Price price={product.price} compareAt={product.compareAtPrice} />
      </View>
    </Pressable>
  );
});

const s = StyleSheet.create({
  cell: { paddingBottom: space.lg },
  pressed: { opacity: 0.85 },
  frame: { backgroundColor: colour.panel, borderWidth: hairline, borderColor: colour.line, overflow: 'hidden' },
  img: { width: '100%', height: '100%' },
  dimmed: { opacity: 0.45 },
  flag: {
    position: 'absolute',
    left: 0,
    bottom: 0,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: colour.ground,
    borderTopWidth: hairline,
    borderRightWidth: hairline,
    borderColor: colour.line,
  },
  flagText: { color: colour.text },
  meta: { paddingTop: space.sm, gap: 2 },
  title: { fontFamily: font.mono, fontSize: 11, lineHeight: 15, letterSpacing: 0.8, textTransform: 'uppercase' },
});
