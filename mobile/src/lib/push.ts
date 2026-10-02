/**
 * Push notifications, client side.
 *
 * The app never asks for permission on launch. It asks at the two moments
 * the answer is obvious: right after an order ("tell me when it ships?") and
 * when the shopper switches on drop alerts. Asked cold, most people say no,
 * and on iPhone a "no" can only be undone in Settings.
 *
 * Each install has a random id. Orders are claimed by that id the moment
 * checkout completes, whether or not notifications are on yet, so switching
 * them on later still covers the order. The push service holds only ids and
 * push tokens — no names, emails or addresses.
 */
import Constants from 'expo-constants';
import * as Crypto from 'expo-crypto';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { colour } from '@/theme/tokens';
import { PUSH_API_URL } from './config';
import { KEYS, readJSON, writeJSON } from './storage';

export type PushState =
  | 'unsupported'   /* web, simulator */
  | 'unconfigured'  /* no push service URL or EAS project yet */
  | 'undetermined'
  | 'denied'
  | 'granted';

const projectId: string | undefined =
  Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId;

let cachedInstall: string | null = null;

export async function installId(): Promise<string> {
  if (cachedInstall) return cachedInstall;
  let id = await readJSON<string | null>(KEYS.installId, null);
  if (!id || !/^[0-9a-f-]{36}$/.test(id)) {
    id = Crypto.randomUUID();
    await writeJSON(KEYS.installId, id);
  }
  cachedInstall = id;
  return id;
}

export async function pushState(): Promise<PushState> {
  if (Platform.OS === 'web' || !Device.isDevice) return 'unsupported';
  if (!PUSH_API_URL || !projectId) return 'unconfigured';
  const { status } = await Notifications.getPermissionsAsync();
  return status === 'granted' ? 'granted' : status === 'denied' ? 'denied' : 'undetermined';
}

async function api(path: string, method: 'POST' | 'PUT', body: unknown): Promise<Response | null> {
  if (!PUSH_API_URL) return null;
  try {
    return await fetch(`${PUSH_API_URL.replace(/\/$/, '')}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    return null;
  }
}

async function ensureChannels(): Promise<void> {
  if (Platform.OS !== 'android') return;
  /* Android 13+ will not show the permission prompt until a channel exists. */
  await Notifications.setNotificationChannelAsync('orders', {
    name: 'Order updates',
    importance: Notifications.AndroidImportance.HIGH,
    lightColor: colour.purple,
  });
  await Notifications.setNotificationChannelAsync('drops', {
    name: 'Drops',
    importance: Notifications.AndroidImportance.DEFAULT,
    lightColor: colour.purple,
  });
}

/**
 * Asks (if not already answered), then registers this device's token with
 * the push service. Safe to call repeatedly — tokens can rotate.
 */
export async function enablePush(): Promise<PushState> {
  const before = await pushState();
  if (before === 'unsupported' || before === 'unconfigured') return before;

  await ensureChannels();
  let status = before;
  if (status !== 'granted') {
    const res = await Notifications.requestPermissionsAsync({
      ios: { allowAlert: true, allowBadge: true, allowSound: true },
    });
    status = res.status === 'granted' ? 'granted' : res.status === 'denied' ? 'denied' : 'undetermined';
  }
  if (status !== 'granted') return status;

  try {
    const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    await api('/v1/devices', 'POST', { installId: await installId(), token, platform: Platform.OS });
  } catch {
    /* permission stands; registration is retried next launch by syncPush() */
  }
  return 'granted';
}

/** On launch: if permission was granted earlier, refresh the token silently. */
export async function syncPush(): Promise<void> {
  if ((await pushState()) === 'granted') await enablePush();
}

/** Ties an order to this install so its shipping updates come here. */
export async function claimOrder(orderId: string): Promise<boolean> {
  const res = await api('/v1/orders/claim', 'POST', { installId: await installId(), orderId });
  return Boolean(res && (res.status === 202 || res.status === 200));
}

export async function setDropAlerts(on: boolean): Promise<boolean> {
  const res = await api('/v1/topics/drops', 'PUT', { installId: await installId(), on });
  const ok = Boolean(res && res.ok);
  if (ok) await writeJSON(KEYS.drops, on);
  return ok;
}

export async function dropAlertsOn(): Promise<boolean> {
  return readJSON<boolean>(KEYS.drops, false);
}
