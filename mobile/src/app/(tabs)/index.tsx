import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native';
import { router } from 'expo-router';
import { ProductTile } from '@/components/ProductTile';
import { Screen } from '@/components/Screen';
import { Failed, Loading } from '@/components/States';
import { Display, Micro, Mono } from '@/components/Type';
import { categoriesOf, getCatalogue } from '@/lib/catalogue';
import type { ProductCard } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { colour, font, hairline, space } from '@/theme/tokens';

const ALL = 'ALL';
const GUTTER = space.lg;
const GAP = space.md;

export default function ShopScreen() {
  const { data, error, loading, reload } = useLoad((signal) => getCatalogue(signal), 'catalogue');
  const [filter, setFilter] = useState(ALL);
  const { width } = useWindowDimensions();
  /* Two columns on a phone, three from a large phone in landscape or a tablet. */
  const cols = width >= 700 ? 3 : 2;
  const tileW = Math.floor((Math.min(width, 1000) - GUTTER * 2 - GAP * (cols - 1)) / cols);

  const cats = useMemo(() => (data ? categoriesOf(data) : []), [data]);
  /* A filter that no longer exists after a refresh falls back to ALL. */
  const active = filter !== ALL && !cats.includes(filter) ? ALL : filter;
  const shown = useMemo(
    () => (data ?? []).filter((p) => active === ALL || p.productType.trim() === active),
    [data, active],
  );

  if (!data) {
    return (
      <Screen>
        {error ? <Failed message={error} onRetry={reload} /> : <Loading label="Loading the catalogue" />}
      </Screen>
    );
  }

  return (
    <Screen aside={`${shown.length} ${shown.length === 1 ? 'item' : 'items'}`}>
      <FlatList
        key={cols}
        data={shown}
        keyExtractor={(p) => p.id}
        numColumns={cols}
        columnWrapperStyle={{ gap: GAP }}
        contentContainerStyle={s.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colour.accent} />}
        ListHeaderComponent={
          <View style={s.head}>
            <Display style={s.h1} accessibilityRole="header">Catalogue</Display>
            {cats.length > 1 ? (
              <Filters cats={cats} active={active} onPick={setFilter} />
            ) : null}
            {error ? <Micro style={s.stale}>Showing the last loaded list — {error}</Micro> : null}
          </View>
        }
        ListEmptyComponent={<Mono style={s.empty}>Nothing in this category yet.</Mono>}
        renderItem={({ item }: { item: ProductCard }) => (
          <ProductTile
            product={item}
            width={tileW}
            onPress={() => router.push({ pathname: '/products/[handle]', params: { handle: item.handle } })}
          />
        )}
      />
    </Screen>
  );
}

function Filters({ cats, active, onPick }: { cats: string[]; active: string; onPick: (c: string) => void }) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={s.filters}
      accessibilityRole="tablist"
      accessibilityLabel="Filter products"
    >
      {[ALL, ...cats].map((c) => {
        const on = c === active;
        return (
          <Pressable
            key={c}
            onPress={() => onPick(c)}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            style={({ pressed }) => [s.chip, on && s.chipOn, pressed && !on && s.chipPressed]}
          >
            <Mono style={[s.chipText, on && s.chipTextOn]}>{c}</Mono>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  list: { paddingHorizontal: GUTTER, paddingBottom: space.xxl, maxWidth: 1000, width: '100%', alignSelf: 'center' },
  head: { paddingTop: space.lg, paddingBottom: space.lg, gap: space.md },
  h1: { fontSize: 40, lineHeight: 40 },
  filters: { gap: 6, paddingRight: GUTTER },
  chip: { minHeight: 36, paddingHorizontal: 12, borderWidth: hairline, borderColor: colour.line, justifyContent: 'center' },
  chipOn: { backgroundColor: colour.purple, borderColor: colour.purple },
  chipPressed: { backgroundColor: colour.press },
  chipText: { fontFamily: font.mono, fontSize: 10, letterSpacing: 2, textTransform: 'uppercase', color: colour.dim },
  chipTextOn: { color: colour.onPurple },
  stale: { color: colour.red },
  empty: { color: colour.dim, paddingVertical: space.xxl, textAlign: 'center' },
});
