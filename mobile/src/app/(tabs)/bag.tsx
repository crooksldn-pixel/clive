import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, Linking, Pressable, StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { Button } from '@/components/Button';
import { Screen } from '@/components/Screen';
import { Empty, Loading } from '@/components/States';
import { Display, Label, Micro, Mono } from '@/components/Type';
import { openCheckout, preloadCheckout } from '@/lib/checkout';
import { orderNumberFromGid } from '@/lib/checkout-types';
import { sized } from '@/lib/image';
import { formatMoney } from '@/lib/money';
import { claimOrder, enablePush, pushState, type PushState } from '@/lib/push';
import type { Cart, CartLine } from '@/lib/types';
import { messageOf, useCart } from '@/state/cart';
import { useOrders } from '@/state/orders';
import { colour, font, hairline, space, TAP } from '@/theme/tokens';

/** How long after opening checkout a vanished cart still means "paid for". */
const CHECKOUT_WINDOW_MS = 60 * 60 * 1000;

type Confirmation = { orderId: string | null };

export default function BagScreen() {
  const { cart, ready, pending, setQuantity, remove, refresh, clear } = useCart();
  const { record } = useOrders();
  const [err, setErr] = useState<string | null>(null);
  const [placed, setPlaced] = useState<Confirmation | null>(null);
  const [opening, setOpening] = useState(false);
  const openedAt = useRef(0);
  const lastCart = useRef<Cart | null>(null);

  const complete = useCallback(
    async (gid: string | null, total: string | null, items: number | null) => {
      openedAt.current = 0;
      const id = orderNumberFromGid(gid);
      await record({ id, placedAt: new Date().toISOString(), total, items, notify: false });
      await clear();
      if (id) claimOrder(id).catch(() => undefined);
      setPlaced({ orderId: id });
    },
    [record, clear],
  );

  /* A browser checkout cannot report back. If the cart disappears soon after
     checkout was opened, Shopify consumed it: the order went through. */
  useEffect(() => {
    const before = lastCart.current;
    lastCart.current = cart;
    if (before && !cart && openedAt.current && Date.now() - openedAt.current < CHECKOUT_WINDOW_MS) {
      complete(null, summaryTotal(before), before.totalQuantity);
    }
  }, [cart, complete]);

  useEffect(() => {
    if (cart?.checkoutUrl && cart.lines.length) preloadCheckout(cart.checkoutUrl);
  }, [cart?.checkoutUrl, cart?.totalQuantity, cart?.lines.length]);

  const onCheckout = async () => {
    if (!cart) return;
    setErr(null);
    setOpening(true);
    openedAt.current = Date.now();
    const snapshot = cart;
    try {
      const r = await openCheckout(cart.checkoutUrl, (gid) => {
        const id = orderNumberFromGid(gid);
        if (id) claimOrder(id).catch(() => undefined);
      });
      if (r.status === 'completed') {
        await complete(r.orderId, r.total ?? summaryTotal(snapshot), r.items ?? snapshot.totalQuantity);
      } else if (r.status === 'failed') {
        openedAt.current = 0;
        if (r.cartGone) await clear();
        setErr(r.message);
      } else {
        await refresh().catch(() => undefined);
      }
    } finally {
      setOpening(false);
    }
  };

  const change = async (job: () => Promise<void>) => {
    setErr(null);
    try {
      await job();
    } catch (e) {
      setErr(messageOf(e));
    }
  };

  if (placed) return <Placed confirmation={placed} onDone={() => setPlaced(null)} />;

  if (!ready) {
    return (
      <Screen>
        <Loading label="Loading your bag" />
      </Screen>
    );
  }

  if (!cart || cart.lines.length === 0) {
    return (
      <Screen>
        <Empty
          title="Bag empty"
          body="Nothing in here yet."
          action={{ label: 'Shop the catalogue', onPress: () => router.navigate('/') }}
        />
      </Screen>
    );
  }

  const notice = err ?? cart.notice;

  return (
    <Screen aside={`${cart.totalQuantity} ${cart.totalQuantity === 1 ? 'item' : 'items'}`}>
      <FlatList
        data={cart.lines}
        keyExtractor={(l) => l.id}
        contentContainerStyle={s.list}
        ListHeaderComponent={<Display style={s.h1} accessibilityRole="header">Bag</Display>}
        renderItem={({ item }) => (
          <Line
            line={item}
            busy={pending.has(item.id)}
            onQty={(q) => change(() => setQuantity(item.id, q))}
            onRemove={() => change(() => remove(item.id))}
          />
        )}
      />
      <View style={s.dock}>
        {notice ? <Mono style={err ? s.err : s.note} accessibilityRole="alert">{notice}</Mono> : null}
        <View style={s.totalRow}>
          <Label>Subtotal</Label>
          <Display style={s.total}>{formatMoney(cart.cost.subtotalAmount)}</Display>
        </View>
        <Micro>Shipping and any discount codes at checkout.</Micro>
        <Button
          big
          label={opening ? 'Opening checkout…' : 'Checkout'}
          busy={opening}
          disabled={pending.size > 0}
          onPress={onCheckout}
          accessibilityHint="Opens Shopify's secure checkout"
        />
      </View>
    </Screen>
  );
}

function summaryTotal(c: Cart): string {
  return formatMoney(c.cost.totalAmount);
}

function Line({ line, busy, onQty, onRemove }: { line: CartLine; busy: boolean; onQty: (q: number) => void; onRemove: () => void }) {
  const m = line.merchandise;
  const opts = m.selectedOptions.filter((o) => o.value !== 'Default Title').map((o) => o.value).join(' / ');
  return (
    <View style={[s.line, busy && s.busy]}>
      <Pressable
        onPress={() => router.push({ pathname: '/products/[handle]', params: { handle: m.product.handle } })}
        accessibilityRole="link"
        accessibilityLabel={`${m.product.title}${opts ? `, ${opts}` : ''}`}
        style={s.thumb}
      >
        {m.image ? <Image source={{ uri: sized(m.image.url, 220) }} style={s.thumbImg} contentFit="contain" /> : null}
      </Pressable>
      <View style={s.lineBody}>
        <Mono style={s.lineTitle} numberOfLines={2}>{m.product.title}</Mono>
        {opts ? <Micro>{opts}</Micro> : null}
        <Mono style={s.linePrice}>{formatMoney(line.cost.totalAmount)}</Mono>
        <View style={s.qtyRow}>
          <Step label="−" a11y={`Remove one ${m.product.title}`} onPress={() => onQty(line.quantity - 1)} disabled={busy} />
          <Mono style={s.qty} accessibilityLabel={`Quantity ${line.quantity}`}>{line.quantity}</Mono>
          <Step label="+" a11y={`Add one more ${m.product.title}`} onPress={() => onQty(line.quantity + 1)} disabled={busy} />
          <Pressable onPress={onRemove} disabled={busy} accessibilityRole="button" accessibilityLabel={`Remove ${m.product.title}`} hitSlop={8} style={s.remove}>
            <Micro style={s.removeText}>Remove</Micro>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

function Step({ label, a11y, onPress, disabled }: { label: string; a11y: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={a11y}
      style={({ pressed }) => [s.step, pressed && s.stepPressed]}
    >
      <Mono style={s.stepText}>{label}</Mono>
    </Pressable>
  );
}

/**
 * After an order. The one moment asking for notifications makes obvious
 * sense — and it is only offered if the push service is actually wired up,
 * so the app never promises an update nobody will send.
 */
function Placed({ confirmation, onDone }: { confirmation: Confirmation; onDone: () => void }) {
  const { markNotify } = useOrders();
  const [state, setState] = useState<PushState | null>(null);
  const [asking, setAsking] = useState(false);
  const id = confirmation.orderId;

  useEffect(() => {
    pushState().then(async (p) => {
      setState(p);
      if (p === 'granted' && id) await markNotify(id);
    });
  }, [id, markNotify]);

  const ask = async () => {
    setAsking(true);
    const p = await enablePush();
    setState(p);
    if (p === 'granted' && id) await markNotify(id);
    setAsking(false);
  };

  const offerPush = Boolean(id) && state !== null && state !== 'unsupported' && state !== 'unconfigured';

  return (
    <Screen>
      <View style={s.placed}>
        <Label>Order received</Label>
        <Display style={s.placedTitle} accessibilityRole="header">Thank you</Display>
        <Mono style={s.placedBody}>
          Shopify is emailing your confirmation now. Tracking is under Orders, any time.
        </Mono>

        {offerPush && state === 'granted' ? (
          <Mono style={s.placedOk}>You will get a notification when it ships.</Mono>
        ) : null}

        {offerPush && state === 'undetermined' ? (
          <View style={s.ask}>
            <Mono>Want a notification when it ships?</Mono>
            <Button label="Notify me" onPress={ask} busy={asking} />
          </View>
        ) : null}

        {offerPush && state === 'denied' ? (
          <View style={s.ask}>
            <Mono style={s.placedBody}>Notifications are off for CROOKSLDN. Turn them on in Settings to hear when it ships.</Mono>
            <Button label="Open settings" variant="ghost" onPress={() => Linking.openSettings()} />
          </View>
        ) : null}

        <View style={s.placedActions}>
          <Button label="Continue shopping" variant="ghost" onPress={() => { onDone(); router.navigate('/'); }} />
          <Button label="View orders" variant="ghost" onPress={() => { onDone(); router.navigate('/orders'); }} />
        </View>
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  list: { paddingHorizontal: space.lg, paddingBottom: space.xl, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: 40, lineHeight: 40, paddingTop: space.lg, paddingBottom: space.md },
  line: { flexDirection: 'row', gap: space.md, paddingVertical: space.md, borderTopWidth: hairline, borderTopColor: colour.line },
  busy: { opacity: 0.5 },
  thumb: { width: 84, height: 105, backgroundColor: colour.panel, borderWidth: hairline, borderColor: colour.line },
  thumbImg: { width: '100%', height: '100%' },
  lineBody: { flex: 1, gap: 4 },
  lineTitle: { fontFamily: font.mono, fontSize: 12, lineHeight: 16, letterSpacing: 0.8, textTransform: 'uppercase' },
  linePrice: { fontSize: 12 },
  qtyRow: { flexDirection: 'row', alignItems: 'center', marginTop: 6 },
  step: { width: TAP, height: 36, borderWidth: hairline, borderColor: colour.line, alignItems: 'center', justifyContent: 'center' },
  stepPressed: { backgroundColor: colour.press },
  stepText: { fontSize: 16, lineHeight: 18 },
  qty: { minWidth: 36, textAlign: 'center' },
  remove: { marginLeft: 'auto', paddingVertical: 8 },
  removeText: { textDecorationLine: 'underline' },
  dock: {
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    paddingBottom: space.md,
    borderTopWidth: hairline,
    borderTopColor: colour.line,
    gap: space.sm,
    backgroundColor: colour.ground,
  },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  total: { fontSize: 30, lineHeight: 30 },
  note: { color: colour.accent, fontSize: 12 },
  err: { color: colour.red, fontSize: 12 },
  placed: { flex: 1, padding: space.xl, justifyContent: 'center', gap: space.md, maxWidth: 520, width: '100%', alignSelf: 'center' },
  placedTitle: { fontSize: 48, lineHeight: 48 },
  placedBody: { color: colour.dim },
  placedOk: { color: colour.accent },
  ask: { gap: space.md, borderTopWidth: hairline, borderTopColor: colour.line, paddingTop: space.lg, marginTop: space.sm },
  placedActions: { gap: space.sm, marginTop: space.xl },
});
