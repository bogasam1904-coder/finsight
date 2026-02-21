import React, { useState, useRef } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform, Animated, StatusBar, ScrollView } from 'react-native';
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

  const shake = () => Animated.sequence([
    Animated.timing(shakeAnim, { toValue: 12, duration: 60, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: -12, duration: 60, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: 8, duration: 60, useNativeDriver: true }),
    Animated.timing(shakeAnim, { toValue: 0, duration: 60, useNativeDriver: true }),
  ]).start();

  const handleLogin = async () => {
    if (!email.trim() || !password) { setError('Please enter email and password'); shake(); return; }
    setLoading(true); setError('');
    try {
      const res = await fetch(`${BACKEND}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || 'Invalid credentials'); shake(); return; }
      await AsyncStorage.setItem('token', data.token);
      await AsyncStorage.setItem('user', JSON.stringify({ name: data.name, email: data.email, user_id: data.user_id }));
      router.replace('/(tabs)');
    } catch { setError('Network error. Please try again.'); shake(); }
    finally { setLoading(false); }
  };

  return (
    <KeyboardAvoidingView style={s.root} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <StatusBar barStyle="light-content" />
      <View style={s.bg}>
        <View style={[s.blob, { width: 380, height: 380, backgroundColor: 'rgba(79,138,255,0.12)', top: -130, right: -110 }]} />
        <View style={[s.blob, { width: 260, height: 260, backgroundColor: 'rgba(34,197,94,0.08)', bottom: -60, left: -80 }]} />
      </View>
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        <TouchableOpacity style={s.back} onPress={() => router.back()}>
          <Text style={s.backText}>← Back</Text>
        </TouchableOpacity>
        <View style={s.logoArea}>
          <Text style={s.logoEmoji}>📊</Text>
          <Text style={s.logoName}>FinSight</Text>
          <Text style={s.logoTag}>Welcome back</Text>
        </View>
        <Animated.View style={[s.card, { transform: [{ translateX: shakeAnim }] }]}>
          <Text style={s.cardTitle}>Sign In</Text>
          {error ? <View style={s.errorBox}><Text style={s.errorText}>⚠ {error}</Text></View> : null}
          <View style={s.field}>
            <Text style={s.fieldLabel}>Email</Text>
            <TextInput style={s.input} placeholder="you@example.com" placeholderTextColor="rgba(255,255,255,0.22)" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" autoComplete="email" />
          </View>
          <View style={s.field}>
            <Text style={s.fieldLabel}>Password</Text>
            <TextInput style={s.input} placeholder="••••••••" placeholderTextColor="rgba(255,255,255,0.22)" value={password} onChangeText={setPassword} secureTextEntry onSubmitEditing={handleLogin} />
          </View>
          <TouchableOpacity style={[s.submitBtn, loading && s.disabled]} onPress={handleLogin} disabled={loading}>
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={s.submitText}>Sign In →</Text>}
          </TouchableOpacity>
          <View style={s.divider}><View style={s.line} /><Text style={s.or}>or</Text><View style={s.line} /></View>
          <TouchableOpacity onPress={() => router.push('/register')} style={{ alignItems: 'center' }}>
            <Text style={s.switchText}>No account? <Text style={s.switchLink}>Create one free</Text></Text>
          </TouchableOpacity>
        </Animated.View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#030B1A' },
  bg: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  blob: { position: 'absolute', borderRadius: 999 },
  scroll: { flexGrow: 1, justifyContent: 'center', paddingHorizontal: 24, paddingTop: 72, paddingBottom: 40 },
  back: { marginBottom: 24 },
  backText: { color: 'rgba(255,255,255,0.45)', fontSize: 15, fontWeight: '600' },
  logoArea: { alignItems: 'center', marginBottom: 36 },
  logoEmoji: { fontSize: 50, marginBottom: 8 },
  logoName: { fontSize: 32, fontWeight: '900', color: '#fff', letterSpacing: -1, marginBottom: 4 },
  logoTag: { color: 'rgba(255,255,255,0.35)', fontSize: 15 },
  card: { backgroundColor: '#0D1426', borderRadius: 24, padding: 28, borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)' },
  cardTitle: { fontSize: 22, fontWeight: '900', color: '#fff', marginBottom: 20, letterSpacing: -0.5 },
  errorBox: { backgroundColor: 'rgba(239,68,68,0.12)', borderRadius: 12, padding: 12, marginBottom: 16, borderWidth: 1, borderColor: 'rgba(239,68,68,0.25)' },
  errorText: { color: '#ef4444', fontSize: 13, fontWeight: '500' },
  field: { marginBottom: 16 },
  fieldLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  input: { backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 14, padding: 16, color: '#fff', fontSize: 15, borderWidth: 1, borderColor: 'rgba(255,255,255,0.09)' },
  submitBtn: { backgroundColor: '#4F8AFF', borderRadius: 16, padding: 17, alignItems: 'center', marginTop: 6 },
  disabled: { opacity: 0.6 },
  submitText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 22, gap: 12 },
  line: { flex: 1, height: 1, backgroundColor: 'rgba(255,255,255,0.07)' },
  or: { color: 'rgba(255,255,255,0.25)', fontSize: 12 },
  switchText: { color: 'rgba(255,255,255,0.35)', fontSize: 14 },
  switchLink: { color: '#4F8AFF', fontWeight: '700' },
});
