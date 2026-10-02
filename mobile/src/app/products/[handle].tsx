import { useMemo, useRef, useState, type Ref } from 'react';
import {
  FlatList,
  Pressable,
  ScrollView,
  StyleSheet,
  useWindowDimensions,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import { Image } from 'expo-image';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Button } from '@/components/Button';
import { NoImage } from '@/components/NoImage';
import { OptionRow, type OptionValue } from '@/components/OptionRow';
import { Price } from '@/components/Price';
import { Empty, Failed, Loading } from '@/components/States';
import { Display, Label, Micro, Mono } from '@/components/Type';
import { getProduct } from '@/lib/catalogue';
import { sized } from '@/lib/image';
import { formatMoney } from '@/lib/money';
import type { MeasureRow, Product, ShopImage } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import {
  initialSelection,
  isSingleVariant,
  isValueAvailable,
  resolveVariant,
  type Selection,
} from '@/lib/variants';
import { messageOf, useCart } from '@/state/cart';
import { colour, font, hairline, space } from '@/theme/tokens';

export default function ProductScreen() {
  const { handle } = useLocalSearchParams<{ handle: string }>();
  const { data, error, reload } = useLoad((signal) => getProduct(String(handle), signal), String(handle));

  if (data === undefined) {
    return error ? <Failed message={error} onRetry={reload} /> : <Loading label="Loading" />;
  }
  if (data === null) {
    return (
      <Empty
        title="Not found"
        body="This piece is no longer listed."
        action={{ label: 'Back to the catalogue', onPress: () => router.navigate('/') }}
      />
    );
  }
  return <ProductView product={data} />;
}

function BagLink() {
  const { cart } = useCart();
  const n = cart?.totalQuantity ?? 0;
  return (
    <Pressable
      onPress={() => router.navigate('/bag')}
      accessibilityRole="link"
      accessibilityLabel={`Bag, ${n} ${n === 1 ? 'item' : 'items'}`}
      hitSlop={10}
    >
      <Mono style={s.bagLink}>{n > 0 ? `BAG (${n})` : 'BAG'}</Mono>
    </Pressable>
  );
}

function ProductView({ product }: { product: Product }) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const { add, pending } = useCart();
  const [sel, setSel] = useState<Selection>(() => initialSelection(product));
  const [added, setAdded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const gallery = useRef<FlatList<ShopImage>>(null);

  const single = isSingleVariant(product);
  const variant = single ? product.variants[0] : resolveVariant(product, sel);
  const busy = pending.has('add');
  const firstOpen = product.options.find((o) => !sel[o.name]);

  const images = product.images.length ? product.images : product.featuredImage ? [product.featuredImage] : [];

  const pick = (option: string, value: string) => {
    let next: Selection = { ...sel, [option]: value };
    /* If that combination does not exist in stock, keep the new choice and
       drop the others rather than leave a selection that can never be bought. */
    const anyBuyable = product.variants.some(
      (v) => v.availableForSale && v.selectedOptions.every((so) => !next[so.name] || next[so.name] === so.value),
    );
    if (!anyBuyable) {
      next = { ...initialSelection(product), [option]: value };
    }
    setSel(next);
    setAdded(false);
    setErr(null);

    /* A colour with its own photograph brings that photograph forward. */
    const v = resolveVariant(product, next);
    const at = v?.image ? images.findIndex((i) => i.url === v.image?.url) : -1;
    if (at >= 0) gallery.current?.scrollToIndex({ index: at, animated: true });
  };

  const onAdd = async () => {
    if (!variant) return;
    setErr(null);
    try {
      await add(variant.id, 1);
      setAdded(true);
    } catch (e) {
      setErr(messageOf(e));
    }
  };

  let cta: string;
  let ready = false;
  if (!product.availableForSale) cta = 'Sold out';
  else if (!variant) cta = `Select ${(firstOpen?.name ?? 'size').toLowerCase()}`;
  else if (!variant.availableForSale) cta = 'Sold out in this choice';
  else {
    cta = `Add to bag — ${formatMoney(variant.price)}`;
    ready = true;
  }

  return (
    <View style={s.root}>
      <Stack.Screen options={{ title: '', headerRight: () => <BagLink /> }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 120 + insets.bottom }}>
        <Gallery images={images} width={width} ref={gallery} title={product.title} />

        <View style={s.body}>
          <View style={s.titleBlock}>
            {product.productType ? <Label>{product.productType}</Label> : null}
            <Display style={s.title} accessibilityRole="header">{product.title}</Display>
            {product.subtitle ? <Mono style={s.subtitle}>{product.subtitle}</Mono> : null}
            <Price
              big
              price={variant?.price ?? product.price}
              compareAt={variant ? (variant.compareAtPrice && Number(variant.compareAtPrice.amount) > Number(variant.price.amount) ? variant.compareAtPrice : null) : product.compareAtPrice}
            />
          </View>

          {!single
            ? product.options.map((o) => (
                <OptionRow
                  key={o.name}
                  option={o.name}
                  selected={sel[o.name]}
                  onSelect={(v) => pick(o.name, v)}
                  values={o.optionValues.map<OptionValue>((ov) => {
                    const soldOut = !isValueAvailable(product, {}, o.name, ov.name);
                    return {
                      name: ov.name,
                      soldOut,
                      unavailableHere: !soldOut && !isValueAvailable(product, sel, o.name, ov.name),
                    };
                  })}
                />
              ))
            : null}

          {product.description ? (
            <View style={s.section}>
              <Label>Description</Label>
              <Mono style={s.desc}>{product.description}</Mono>
            </View>
          ) : null}

          {product.measurements ? <SizeChart rows={product.measurements} /> : null}
        </View>
      </ScrollView>

      <View style={[s.dock, { paddingBottom: Math.max(insets.bottom, space.md) }]}>
        {err ? <Mono style={s.err} accessibilityRole="alert">{err}</Mono> : null}
        {added ? (
          <View style={s.addedRow} accessibilityLiveRegion="polite">
            <Button label="Added — view bag" onPress={() => router.navigate('/bag')} style={s.flex} />
          </View>
        ) : (
          <Button big label={busy ? 'Adding…' : cta} onPress={onAdd} disabled={!ready} busy={busy} />
        )}
      </View>
    </View>
  );
}

type GalleryProps = { images: ShopImage[]; width: number; title: string; ref: Ref<FlatList<ShopImage>> };

function Gallery({ images, width, title, ref }: GalleryProps) {
  const [at, setAt] = useState(0);
  const h = Math.round(Math.min(width * 1.15, 620));
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const i = Math.round(e.nativeEvent.contentOffset.x / width);
    if (i !== at) setAt(i);
  };
  if (!images.length) {
    return (
      <View style={[s.galleryEmpty, { height: h }]}>
        <NoImage size={96} />
      </View>
    );
  }
  return (
    <View>
      <FlatList
        ref={ref}
        data={images}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        keyExtractor={(i, n) => `${n}-${i.url}`}
        onScroll={onScroll}
        scrollEventThrottle={32}
        getItemLayout={(_, index) => ({ length: width, offset: width * index, index })}
        renderItem={({ item, index }) => (
          <View style={[s.slide, { width, height: h }]}>
            <Image
              source={{ uri: sized(item.url, width * 2) }}
              style={s.slideImg}
              contentFit="contain"
              transition={150}
              accessibilityLabel={item.altText || `${title}, image ${index + 1} of ${images.length}`}
            />
          </View>
        )}
      />
      {images.length > 1 ? (
        <Micro style={s.counter} accessibilityElementsHidden importantForAccessibility="no">
          {String(at + 1).padStart(2, '0')} / {String(images.length).padStart(2, '0')}
        </Micro>
      ) : null}
    </View>
  );
}

function SizeChart({ rows }: { rows: MeasureRow[] }) {
  const cols = useMemo(() => Object.keys(rows[0] ?? {}), [rows]);
  if (!cols.length) return null;
  return (
    <View style={s.section}>
      <Label>Measurements</Label>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={s.table} accessibilityRole="summary">
          <View style={[s.tr, s.thead]}>
            {cols.map((c) => (
              <Micro key={c} style={s.td}>{c}</Micro>
            ))}
          </View>
          {rows.map((r, i) => (
            <View key={i} style={s.tr}>
              {cols.map((c) => (
                <Mono key={c} style={[s.td, s.tdText]}>{r[c] ?? '—'}</Mono>
              ))}
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colour.ground },
  bagLink: { fontFamily: font.mono, fontSize: 11, letterSpacing: 2, color: colour.text, paddingHorizontal: 4 },
  slide: { backgroundColor: colour.panel, alignItems: 'center', justifyContent: 'center' },
  slideImg: { width: '100%', height: '100%' },
  galleryEmpty: { backgroundColor: colour.panel },
  counter: { position: 'absolute', right: space.lg, bottom: space.md, color: colour.text },
  body: { paddingHorizontal: space.lg, paddingTop: space.xl, gap: space.xl, maxWidth: 640, width: '100%', alignSelf: 'center' },
  titleBlock: { gap: space.sm },
  title: { fontSize: 38, lineHeight: 38 },
  subtitle: { color: colour.dim },
  section: { gap: space.sm, borderTopWidth: hairline, borderTopColor: colour.line, paddingTop: space.lg },
  desc: { color: colour.text },
  table: { borderWidth: hairline, borderColor: colour.line },
  tr: { flexDirection: 'row', borderTopWidth: hairline, borderTopColor: colour.line },
  thead: { borderTopWidth: 0, backgroundColor: colour.panel },
  td: { width: 78, paddingVertical: 8, paddingHorizontal: 10 },
  tdText: { fontSize: 12 },
  dock: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    backgroundColor: colour.ground,
    borderTopWidth: hairline,
    borderTopColor: colour.line,
    gap: space.sm,
  },
  addedRow: { flexDirection: 'row', gap: space.sm },
  flex: { flex: 1, minHeight: 58 },
  err: { color: colour.red, fontSize: 12 },
});
