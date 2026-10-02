import { router, Stack } from 'expo-router';
import { Empty } from '@/components/States';

export default function NotFound() {
  return (
    <>
      <Stack.Screen options={{ title: '' }} />
      <Empty
        title="Not here"
        body="That page does not exist in the app."
        action={{ label: 'Back to the catalogue', onPress: () => router.replace('/') }}
      />
    </>
  );
}
