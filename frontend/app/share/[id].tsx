import { useEffect } from 'react';
import { View, ActivityIndicator, Text, StyleSheet } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function ShareRedirect() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!id) {
      router.replace('/(tabs)');
      return;
    }

    // Verify analysis exists, then redirect to main analysis view
    const checkAnalysis = async () => {
      try {
        const res = await fetch(`${BACKEND}/api/public/analyses/${id}`);
        if (res.ok) {
          router.replace(`/analysis/${id}`);
        } else {
          router.replace('/(tabs)');
        }
      } catch (error) {
        console.error('Share route error:', error);
        router.replace('/(tabs)');
      }
    };

    checkAnalysis();
  }, [id]);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#4F8AFF" />
      <Text style={styles.text}>Loading analysis...</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#060B18',
  },
  text: {
    color: '#6B82A8',
    marginTop: 14,
    fontSize: 15,
  },
});
