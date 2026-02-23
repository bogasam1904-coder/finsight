import React, { useState, useRef } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, KeyboardAvoidingView, Platform, Animated, StatusBar, ScrollView, Alert
} from 'react-native';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const shakeAnim = useRef(new Animated.Value(0)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  React.useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 600, useNativeDriver: true }).start();
  }, []);

  const shake = () => Animated.sequence([
    Animated.timing(shakeAnim, { toValue: 14, duration: 55, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: -14, duration: 55, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: 10, duration: 55, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: -10, duration: 55, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: 0, duration: 55, useNativeDriver: true }),
  ]).start();

  const handleLogin = async () => {
    const trimEmail = email.trim().toLowerCase();
    if (!trimEmail || !password) {
      setError('Please enter your email and password');
      shake();
      return;
    }
    
    setLoading(true);
    setError('');
    
    try {
      const res = await fetch(`${BACKEND}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ email: trimEmail, password }),
      });
      
      // Parse response
      let data: any;
      const text = await res.text();
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error(`Server error (${res.status}): ${text.substring(0, 100)}`);
      }
      
      if (!res.ok) {
        throw new Error(data.detail || data.message || `Login failed (${res.status})`);
      }
      
      if (!data.token) {
        throw new Error('No token received from server');
      }
      
      // Save to storage
      await AsyncStorage.setItem('token', data.token);
      await AsyncStorage.setItem('user', JSON.stringify({
        name: data.name,
        email: data.email,
        user_id: data.user_id
      }));
      
      // Navigate to tabs
      router.replace('/(tabs)');
      
    } catch (e: any) {
      const msg = e.message || 'Sign in failed. Please try again.';
      setError(msg);
      shake();
    } finally {
      setLoading(false);
    }
  };

  const continueAsGuest = () => {
    router.replace('/(tabs)');
  };

  return (
    <KeyboardAvoidingView style={s.root} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <StatusBar barStyle="light-content" />
      <View style={s.bg}>
        <View style={[s.blob, { width: 380, height: 380, backgroundColor: 'rgba(79,138,255,0.11)', top: -130, right: -110 }]} />
        <View style={[s.blob, { width: 260, height: 260, backgroundColor: 'rgba(34,197,94,0.07)', bottom: -60, left: -80 }]} />
      </View>
      
      <Animated.ScrollView
        contentContainerStyle={s.scroll}
        keyboardShouldPersistTaps="handled"
        style={{ opacity: fadeAnim }}
        showsVerticalScrollIndicator={false}
      >
        <TouchableOpacity style={s.back} onPress={() => router.canGoBack() ? router.back() : router.replace('/')}>
          <Text style={s.backText}>← Back</Text>
        </TouchableOpacity>

        <View style={s.logoArea}>
          <Text style={s.emoji}>📊</Text>
          <Text style={s.appName}>FinSight</Text>
          <Text style={s.tagline}>Welcome back</Text>
        </View>

        <Animated.View style={[s.card, { transform: [{ translateX: shakeAnim }] }]}>
          <Text style={s.cardTitle}>Sign In</Text>

          {error ? (
            <View style={s.errorBox}>
              <Text style={s.errorIcon}>⚠</Text>
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}

          <View style={s.field}>
            <Text style={s.label}>Email</Text>
            <TextInput
              style={s.input}
              placeholder="you@example.com"
              placeholderTextColor="rgba(255,255,255,0.2)"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              autoComplete="email"
              textContentType="emailAddress"
            />
          </View>

          <View style={s.field}>
            <Text style={s.label}>Password</Text>
            <TextInput
              style={s.input}
              placeholder="••••••••"
              placeholderTextColor="rgba(255,255,255,0.2)"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoComplete="password"
              textContentType="password"
              onSubmitEditing={handleLogin}
              returnKeyType="done"
            />
          </View>

          <TouchableOpacity
            style={[s.submitBtn, loading && s.btnDisabled]}
            onPress={handleLogin}
            disabled={loading}
          >
            {loading
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.submitText}>Sign In →</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity style={s.guestBtn} onPress={continueAsGuest}>
            <Text style={s.guestBtnText}>Continue without account →</Text>
          </TouchableOpacity>

          <View style={s.divider}>
            <View style={s.line} />
            <Text style={s.or}>or</Text>
            <View style={s.line} />
          </View>

          <TouchableOpacity onPress={() => router.push('/register')} style={{ alignItems: 'center' }}>
            <Text style={s.switchText}>
              No account? <Text style={s.switchLink}>Create one free</Text>
            </Text>
          </TouchableOpacity>
        </Animated.View>
      </Animated.ScrollView>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#060B18' },
  bg: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  blob: { position: 'absolute', borderRadius: 999 },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingTop: 70, paddingBottom: 40 },
  back: { marginBottom: 24 },
  backText: { color: 'rgba(255,255,255,0.4)', fontSize: 15, fontWeight: '600' },
  logoArea: { alignItems: 'center', marginBottom: 36 },
  emoji: { fontSize: 52, marginBottom: 10 },
  appName: { fontSize: 34, fontWeight: '900', color: '#fff', letterSpacing: -1, marginBottom: 4 },
  tagline: { color: 'rgba(255,255,255,0.35)', fontSize: 15 },
  card: { backgroundColor: '#0D1426', borderRadius: 24, padding: 28, borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)' },
  cardTitle: { fontSize: 22, fontWeight: '900', color: '#fff', marginBottom: 20, letterSpacing: -0.5 },
  errorBox: { backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 14, padding: 14, marginBottom: 18, borderWidth: 1, borderColor: 'rgba(239,68,68,0.22)', flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  errorIcon: { fontSize: 14, color: '#ef4444' },
  errorText: { color: '#ef4444', fontSize: 13, fontWeight: '500', flex: 1, lineHeight: 20 },
  field: { marginBottom: 16 },
  label: { color: 'rgba(255,255,255,0.38)', fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  input: { backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 14, padding: 16, color: '#fff', fontSize: 15, borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)' },
  submitBtn: { backgroundColor: '#4F8AFF', borderRadius: 16, padding: 17, alignItems: 'center', marginTop: 6 },
  btnDisabled: { opacity: 0.6 },
  submitText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  guestBtn: { alignItems: 'center', paddingVertical: 14 },
  guestBtnText: { color: 'rgba(255,255,255,0.35)', fontSize: 13, fontWeight: '500' },
  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 10, gap: 12 },
  line: { flex: 1, height: 1, backgroundColor: 'rgba(255,255,255,0.06)' },
  or: { color: 'rgba(255,255,255,0.2)', fontSize: 12 },
  switchText: { color: 'rgba(255,255,255,0.35)', fontSize: 14 },
  switchLink: { color: '#4F8AFF', fontWeight: '700' },
});
