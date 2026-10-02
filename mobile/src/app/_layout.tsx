import { useEffect } from 'react';
import { Platform } from 'react-native';
import { SpaceMono_400Regular, SpaceMono_700Bold } from '@expo-google-fonts/space-mono';
import { VT323_400Regular } from '@expo-google-fonts/vt323';
import { useFonts } from 'expo-font';
import * as Notifications from 'expo-notifications';
import { DarkTheme, router, SplashScreen, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as WebBrowser from 'expo-web-browser';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { syncPush } from '@/lib/push';
import { CartProvider } from '@/state/cart';
import { OrdersProvider } from '@/state/orders';
import { colour, font } from '@/theme/tokens';

SplashScreen.preventAutoHideAsync().catch(() => undefined);

if (Platform.OS !== 'web') {
  /* A notification that arrives while the app is open still shows. */
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

const theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colour.ground,
    card: colour.ground,
    border: colour.line,
    text: colour.text,
    primary: colour.accent,
  },
};

/**
 * A tapped notification carries `url`: an app path ("/products/v1-hoodie",
 * "/orders") or a carrier's tracking page, which opens in-app.
 */
function openFromNotification(n: Notifications.Notification) {
  const url = n.request.content.data?.url;
  if (typeof url !== 'string' || !url) return;
  if (url.startsWith('/')) router.push(url as never);
  else if (/^https:\/\//.test(url)) WebBrowser.openBrowserAsync(url).catch(() => undefined);
}

function useNotificationTaps() {
  useEffect(() => {
    if (Platform.OS === 'web') return;
    const last = Notifications.getLastNotificationResponse();
    if (last?.notification) openFromNotification(last.notification);
    const sub = Notifications.addNotificationResponseReceivedListener((r) => openFromNotification(r.notification));
    return () => sub.remove();
  }, []);
}

export default function RootLayout() {
  const [loaded, failed] = useFonts({ VT323_400Regular, SpaceMono_400Regular, SpaceMono_700Bold });
  useNotificationTaps();

  useEffect(() => {
    if (loaded || failed) SplashScreen.hideAsync().catch(() => undefined);
  }, [loaded, failed]);

  useEffect(() => {
    syncPush().catch(() => undefined);
  }, []);

  /* Hold the splash until the faces are in: no flash of a fallback font. */
  if (!loaded && !failed) return null;

  return (
    <SafeAreaProvider>
      <ThemeProvider value={theme}>
        <OrdersProvider>
          <CartProvider>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: colour.ground },
                headerTintColor: colour.text,
                headerTitleStyle: { fontFamily: font.mono, fontSize: 12 },
                headerShadowVisible: false,
                headerBackButtonDisplayMode: 'minimal',
                contentStyle: { backgroundColor: colour.ground },
              }}
            >
              <Stack.Screen name="(tabs)" options={{ headerShown: false, title: 'Shop' }} />
              <Stack.Screen name="products/[handle]" options={{ title: '' }} />
            </Stack>
          </CartProvider>
        </OrdersProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
