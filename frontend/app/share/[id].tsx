import { useEffect } from 'react';
import { View, ActivityIndicator, Text } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

const BACKEND = 'https://loyal-integrity-production-2b54.up.railway.app';

export default function ShareRedirect() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!id) {
      router.replace('/(tabs)');
      return;
    }

    // Verify analysis exists, then redirect to main analysis view
    fetch(`${BACKEND}/api/public/analyses/${id}`)
      .then(res => {
        if (res.ok) {
          router.replace(`/analysis/${id}`);
        } else {
          router.replace('/(tabs)');
        }
      })
      .catch(() => router.replace('/(tabs)'));
  }, [id]);

  return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#060B18' }}>
      <ActivityIndicator size="large" color="#4F8AFF" />
      <Text style={{ color: '#6B82A8', marginTop: 14, fontSize: 15 }}>Loading analysis...</Text>
    </View>
  );
}