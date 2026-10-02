import { useCallback, useState } from 'react';
import { Linking, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Button } from '@/components/Button';
import { Screen } from '@/components/Screen';
import { Display, Label, Micro, Mono } from '@/components/Type';
import { ACCOUNT_URL, HELP_PAGES, ORDER_LOOKUP_URL } from '@/lib/config';
import { dropAlertsOn, enablePush, pushState, setDropAlerts, type PushState } from '@/lib/push';
import { useOrders, type PlacedOrder } from '@/state/orders';
import { colour, hairline, space } from '@/theme/tokens';

function open(url: string) {
  WebBrowser.openBrowserAsync(url, {
    controlsColor: colour.accent,
    toolbarColor: colour.ground,
  }).catch(() => Linking.openURL(url));
}

const date = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

export default function OrdersScreen() {
  const { orders } = useOrders();
  const [push, setPush] = useState<PushState | null>(null);
  const [drops, setDrops] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  /* Re-read on focus: the shopper may have changed it in Settings meanwhile. */
  useFocusEffect(
    useCallback(() => {
      pushState().then(setPush);
      dropAlertsOn().then(setDrops);
    }, []),
  );

  const toggleDrops = async (on: boolean) => {
    setNote(null);
    setSaving(true);
    try {
      if (on) {
        const p = await enablePush();
        setPush(p);
        if (p !== 'granted') {
          setNote(p === 'denied' ? 'Notifications are off for CROOKSLDN in Settings.' : 'Notifications were not switched on.');
          return;
        }
      }
      const ok = await setDropAlerts(on);
      if (ok) setDrops(on);
      else setNote('Could not save that. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  const pushAvailable = push !== null && push !== 'unsupported' && push !== 'unconfigured';

  return (
    <Screen>
      <ScrollView contentContainerStyle={s.body}>
        <Display style={s.h1} accessibilityRole="header">Orders</Display>

        <View style={s.actions}>
          <Button label="Track an order" onPress={() => open(ORDER_LOOKUP_URL)} accessibilityHint="Order number and email" />
          <Button label="Sign in for full order history" variant="ghost" onPress={() => open(ACCOUNT_URL)} />
        </View>

        <View style={s.section}>
          <Label>Placed in this app</Label>
          {orders.length ? (
            orders.map((o, i) => <OrderRow key={o.id ?? `${o.placedAt}-${i}`} order={o} />)
          ) : (
            <Mono style={s.dim}>Nothing yet. Orders placed in the app show up here; website orders are in your account.</Mono>
          )}
        </View>

        {pushAvailable ? (
          <View style={s.section}>
            <Label>Notifications</Label>
            <View style={s.toggle}>
              <View style={s.flex}>
                <Mono>Drop alerts</Mono>
                <Micro>When new pieces land. Nothing else.</Micro>
              </View>
              <Switch
                value={drops}
                onValueChange={toggleDrops}
                disabled={saving}
                trackColor={{ false: colour.tray, true: colour.purple }}
                thumbColor={colour.text}
                ios_backgroundColor={colour.tray}
                accessibilityLabel="Drop alerts"
              />
            </View>
            <Micro>
              {push === 'granted'
                ? 'Shipping updates are on for orders placed in this app.'
                : push === 'denied'
                  ? 'Notifications are off for CROOKSLDN.'
                  : 'You will be asked once, when you switch something on.'}
            </Micro>
            {push === 'denied' ? (
              <Button label="Open settings" variant="ghost" onPress={() => Linking.openSettings()} />
            ) : null}
            {note ? <Mono style={s.err} accessibilityRole="alert">{note}</Mono> : null}
          </View>
        ) : null}

        <View style={s.section}>
          <Label>Help</Label>
          {HELP_PAGES.map((p) => (
            <Pressable
              key={p.url}
              onPress={() => open(p.url)}
              accessibilityRole="link"
              style={({ pressed }) => [s.link, pressed && s.linkPressed]}
            >
              <Mono>{p.label}</Mono>
              <Mono style={s.dim}>→</Mono>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </Screen>
  );
}

function OrderRow({ order }: { order: PlacedOrder }) {
  const when = new Date(order.placedAt);
  const items = order.items != null ? `${order.items} ${order.items === 1 ? 'item' : 'items'}` : null;
  return (
    <View style={s.order}>
      <View style={s.flex}>
        <Mono>{Number.isNaN(when.getTime()) ? 'Order' : date.format(when)}</Mono>
        <Micro>{[items, order.total].filter(Boolean).join(' · ')}</Micro>
      </View>
      {order.notify ? <Micro style={s.on}>Alerts on</Micro> : null}
    </View>
  );
}

const s = StyleSheet.create({
  body: { padding: space.lg, gap: space.xl, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: 40, lineHeight: 40 },
  actions: { gap: space.sm },
  section: { gap: space.md, borderTopWidth: hairline, borderTopColor: colour.line, paddingTop: space.lg },
  dim: { color: colour.dim },
  err: { color: colour.red, fontSize: 12 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1, gap: 2 },
  order: { flexDirection: 'row', alignItems: 'center', paddingVertical: space.sm },
  on: { color: colour.accent },
  link: {
    minHeight: 44,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottomWidth: hairline,
    borderBottomColor: colour.line,
  },
  linkPressed: { backgroundColor: colour.press },
});
