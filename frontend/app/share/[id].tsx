// app/share/[id].tsx
// This file should be placed in your app directory structure
// It handles the public share URLs like: https://yourapp.com/share/analysis-id-123

import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function ShareRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Verify the analysis exists, then redirect to the main analysis view
    const checkAndRedirect = async () => {
      if (!id) {
        router.replace('/(tabs)');
        return;
      }

      try {
        // Check if analysis exists via public endpoint
        const res = await fetch(`${BACKEND}/api/public/analyses/${id}`);
        if (res.ok) {
          // Analysis exists, redirect to the analysis view
          router.replace(`/analysis/${id}`);
        } else {
          // Analysis not found
          router.replace('/(tabs)');
        }
      } catch (error) {
        console.error('Error checking analysis:', error);
        router.replace('/(tabs)');
      }
    };

    checkAndRedirect();
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
