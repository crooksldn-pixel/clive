import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * Small JSON store on the device. Every read tolerates a missing or corrupt
 * value — losing a remembered bag id is an inconvenience, crashing on launch
 * because of one is not.
 */
export async function readJSON<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export async function writeJSON(key: string, value: unknown): Promise<void> {
  try {
    if (value === undefined || value === null) await AsyncStorage.removeItem(key);
    else await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or unavailable: the app keeps working for this session */
  }
}

export const KEYS = {
  cartId: 'crooks.cart.id',
  orders: 'crooks.orders',
  installId: 'crooks.install.id',
  drops: 'crooks.push.drops',
} as const;
