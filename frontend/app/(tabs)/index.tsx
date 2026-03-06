// COMPLETE FILE - app/(tabs)/index.tsx
// WITH DEBUG LOGGING TO DIAGNOSE THE ISSUE

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView,
  ActivityIndicator, Alert, Platform, Animated, StatusBar, Dimensions
} from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width } = Dimensions.get('window');
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function HomeTab() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState('');
  const [recent, setRecent] = useState<any[]>([]);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 700, useNativeDriver: false }).start();
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulseAnim, { toValue: 1.018, duration: 2800, useNativeDriver: false }),
      Animated.timing(pulseAnim, { toValue: 1, duration: 2800, useNativeDriver: false }),
    ]));
    loop.start();
    return () => loop.stop();
  }, []);

  useFocusEffect(useCallback(() => {
    loadUser();
    loadRecent();
  }, []));

  const loadUser = async () => {
    const u = await AsyncStorage.getItem('user');
    setUser(u ? JSON.parse(u) : null);
  };

  const loadRecent = async () => {
    const token = await AsyncStorage.getItem('token');
    if (!token) return;
    try {
      const res = await fetch(`${BACKEND}/api/analyses`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setRecent(data.slice(0, 3));
      }
    } catch { }
  };

  // ✅ UPDATED WITH DEBUG LOGGING
  const uploadFile = async (uri: string, name: string, type: string) => {
    setUploading(true);
    setProgress('Uploading...');
    
    // DEBUG: Log upload start
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log('🆕 NEW UPLOAD STARTING');
    console.log('📄 Filename:', name);
    console.log('📁 Type:', type);
    console.log('⏰ Timestamp:', new Date().toISOString());
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    
    try {
      const token = await AsyncStorage.getItem('token');
      const formData = new FormData();

      if (Platform.OS === 'web') {
        setProgress('Reading file...');
        const resp = await fetch(uri);
        const blob = await resp.blob();
        formData.append('file', blob, name);
        console.log('📦 Blob size:', blob.size, 'bytes');
      } else {
        formData.append('file', { uri, type, name } as any);
      }

      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      setProgress('Analysing with AI...');
      console.log('🚀 Calling backend /api/analyze...');
      console.log('🔗 Backend URL:', BACKEND);
      
      const res = await fetch(`${BACKEND}/api/analyze`, { method: 'POST', headers, body: formData });

      console.log('📡 Response status:', res.status);
      console.log('📡 Response OK:', res.ok);

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        console.error('❌ Backend error response:', errData);
        throw new Error(errData.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      
      // DEBUG: Log complete response
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      console.log('✅ BACKEND RESPONSE RECEIVED:');
      console.log('🆔 analysis_id:', data.analysis_id);
      console.log('📊 status:', data.status);
      console.log('📄 filename (in response):', data.filename);
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      console.log('📈 RESULT DATA:');
      console.log('🏢 company_name:', data.result?.company_name);
      console.log('📅 period:', data.result?.period);
      console.log('💯 health_score:', data.result?.health_score);
      console.log('🏷️ statement_type:', data.result?.statement_type);
      console.log('💰 currency:', data.result?.currency);
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      
      setProgress('Done!');
      
      setTimeout(() => {
        setUploading(false);
        setProgress('');
        if (data.status === 'completed' && data.analysis_id) {
          console.log('🔀 REDIRECTING TO:', `/analysis/${data.analysis_id}`);
          console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
          router.push(`/analysis/${data.analysis_id}`);
        } else {
          console.error('⚠️ Analysis not completed. Status:', data.status);
          console.error('⚠️ Message:', data.message);
          Alert.alert('Analysis Failed', data.message || 'Please try another document.');
        }
      }, 400);
    } catch (e: any) {
      console.error('💥 UPLOAD ERROR:', e);
      console.error('💥 Error message:', e.message);
      console.error('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
      setUploading(false);
      setProgress('');
      Alert.alert('Error', e.message || 'Upload failed. Please try again.');
    }
  };

  const pickPDF = async () => {
    try {
      const r = await DocumentPicker.getDocumentAsync({ type: 'application/pdf', copyToCacheDirectory: true });
      if (r.canceled || !r.assets?.[0]) return;
      const f = r.assets[0];
      await uploadFile(f.uri, f.name, 'application/pdf');
    } catch { Alert.alert('Error', 'Could not open file picker'); }
  };

  const pickImage = async () => {
    try {
      const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.9 });
      if (r.canceled || !r.assets?.[0]) return;
      const a = r.assets[0];
      await uploadFile(a.uri, a.fileName || 'image.jpg', a.type || 'image/jpeg');
    } catch { Alert.alert('Error', 'Could not open image picker'); }
  };

  const scoreColor = (s: number) => s >= 80 ? '#22c55e' : s >= 60 ? '#f59e0b' : '#ef4444';

  const timeAgo = (d: string) => {
    const diff = Date.now() - new Date(d).getTime();
    const h = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    if (h < 1) return 'Just now';
    if (h < 24) return `${h}h ago`;
    return `${days}d ago`;
  };

  return (
    <View style={s.root}>
      <StatusBar barStyle="light-content" />
      <View style={s.bgBlobs}>
        <View style={[s.blob, { width: 360, height: 360, backgroundColor: 'rgba(79,138,255,0.11)', top: -120, right: -120 }]} />
        <View style={[s.blob, { width: 240, height: 240, backgroundColor: 'rgba(34,197,94,0.07)', bottom: 200, left: -80 }]} />
      </View>

      <Animated.ScrollView style={[s.scroll, { opacity: fadeAnim }]} showsVerticalScrollIndicator={false}>

        {/* Header */}
        <View style={s.header}>
          <View>
            {user ? (
              <>
                <Text style={s.greeting}>Good day,</Text>
                <Text style={s.userName}>{user.name?.split(' ')[0]} 👋</Text>
              </>
            ) : (
              <>
                <Text style={s.greeting}>Welcome to</Text>
                <Text style={s.userName}>FinSight 📊</Text>
              </>
            )}
          </View>
          <TouchableOpacity
            style={s.searchShortcut}
            onPress={() => router.push('/(tabs)/search')}
          >
            <Text style={s.searchShortcutIcon}>🔍</Text>
          </TouchableOpacity>
        </View>

        {/* Guest banner */}
        {!user && (
          <View style={s.guestBanner}>
            <View style={s.guestBannerLeft}>
              <Text style={s.guestBannerTitle}>💎 Free account unlocks history</Text>
              <Text style={s.guestBannerSub}>Save & revisit all your analyses</Text>
            </View>
            <View style={s.guestBannerBtns}>
              <TouchableOpacity style={s.guestSignIn} onPress={() => router.push('/login')}>
                <Text style={s.guestSignInText}>Sign In</Text>
              </TouchableOpacity>
              <TouchableOpacity style={s.guestRegister} onPress={() => router.push('/register')}>
                <Text style={s.guestRegisterText}>Join Free</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Upload zone */}
        <Animated.View style={[s.uploadZone, { transform: [{ scale: pulseAnim }] }]}>
          {uploading ? (
            <View style={s.uploading}>
              <ActivityIndicator size="large" color="#4F8AFF" />
              <Text style={s.uploadingTitle}>Analysing...</Text>
              <Text style={s.uploadingProg}>{progress}</Text>
              <View style={s.uploadingBarBg}><View style={s.uploadingBarFill} /></View>
            </View>
          ) : (
            <>
              <View style={s.uploadIconWrap}><Text style={s.uploadIcon}>📄</Text></View>
              <Text style={s.uploadTitle}>Upload Financial Document</Text>
              <Text style={s.uploadSub}>
                Annual reports, quarterly results, balance sheets — full AI analysis in under 30 seconds
              </Text>
              <View style={s.uploadBtns}>
                <TouchableOpacity style={s.btnPrimary} onPress={pickPDF}>
                  <Text style={s.btnPrimaryText}>📄  Upload PDF</Text>
                </TouchableOpacity>
                <TouchableOpacity style={s.btnSecondary} onPress={pickImage}>
                  <Text style={s.btnSecondaryText}>🖼  Image</Text>
                </TouchableOpacity>
              </View>
              <Text style={s.uploadHint}>Free · No account needed to try</Text>
            </>
          )}
        </Animated.View>

        {/* Quick stats */}
        <View style={s.statsRow}>
          {[
            { icon: '⚡', val: '<30s', lbl: 'Analysis Time' },
            { icon: '📊', val: '15+', lbl: 'Metrics Tracked' },
            { icon: '🎯', val: '98%', lbl: 'AI Accuracy' },
          ].map((st, i) => (
            <View key={i} style={s.statCard}>
              <Text style={s.statIcon}>{st.icon}</Text>
              <Text style={s.statVal}>{st.val}</Text>
              <Text style={s.statLbl}>{st.lbl}</Text>
            </View>
          ))}
        </View>

        {/* NSE Search shortcut */}
        <TouchableOpacity style={s.searchCard} onPress={() => router.push('/(tabs)/search')}>
          <View style={s.searchCardLeft}>
            <Text style={s.searchCardIcon}>🔍</Text>
            <View>
              <Text style={s.searchCardTitle}>Search NSE Companies</Text>
              <Text style={s.searchCardSub}>Find annual reports for 100+ listed companies</Text>
            </View>
          </View>
          <Text style={s.searchCardArrow}>→</Text>
        </TouchableOpacity>

        {/* Recent analyses */}
        {recent.length > 0 && (
          <View style={s.recentSection}>
            <View style={s.recentHeader}>
              <Text style={s.recentTitle}>Recent Analyses</Text>
              <TouchableOpacity onPress={() => router.push('/(tabs)/history')}>
                <Text style={s.recentViewAll}>View all →</Text>
              </TouchableOpacity>
            </View>
            {recent.map((a, i) => {
              const sc = a.result?.health_score;
              const col = sc ? scoreColor(sc) : '#6B82A8';
              return (
                <TouchableOpacity key={i} style={s.recentCard} onPress={() => router.push(`/analysis/${a.analysis_id}`)}>
                  <View style={s.recentLeft}>
                    <View style={[s.dot, { backgroundColor: a.status === 'completed' ? '#22c55e' : '#ef4444' }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.recentName} numberOfLines={1}>{a.result?.company_name || a.filename}</Text>
                      <Text style={s.recentMeta}>{a.result?.period || ''} · {timeAgo(a.created_at)}</Text>
                    </View>
                  </View>
                  {sc && (
                    <View style={[s.recentScore, { backgroundColor: col + '20' }]}>
                      <Text style={[s.recentScoreText, { color: col }]}>{sc}</Text>
                    </View>
                  )}
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        <View style={{ height: 100 }} />
      </Animated.ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#060B18' },
  bgBlobs: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, overflow: 'hidden' },
  blob: { position: 'absolute', borderRadius: 999 },
  scroll: { flex: 1 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 22, paddingTop: 58, paddingBottom: 22 },
  greeting: { color: 'rgba(255,255,255,0.38)', fontSize: 14, marginBottom: 2 },
  userName: { color: '#fff', fontSize: 26, fontWeight: '900', letterSpacing: -0.5 },
  searchShortcut: { width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.07)', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)' },
  searchShortcutIcon: { fontSize: 18 },
  guestBanner: { marginHorizontal: 20, marginBottom: 16, backgroundColor: 'rgba(79,138,255,0.1)', borderRadius: 18, padding: 16, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderColor: 'rgba(79,138,255,0.2)' },
  guestBannerLeft: { flex: 1 },
  guestBannerTitle: { color: '#fff', fontSize: 14, fontWeight: '700' },
  guestBannerSub: { color: 'rgba(255,255,255,0.4)', fontSize: 12, marginTop: 2 },
  guestBannerBtns: { flexDirection: 'row', gap: 8, marginLeft: 12 },
  guestSignIn: { borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1, borderColor: 'rgba(255,255,255,0.2)' },
  guestSignInText: { color: '#fff', fontSize: 12, fontWeight: '600' },
  guestRegister: { borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: '#4F8AFF' },
  guestRegisterText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  uploadZone: { marginHorizontal: 20, borderRadius: 24, backgroundColor: '#0D1426', borderWidth: 1.5, borderColor: 'rgba(79,138,255,0.2)', borderStyle: 'dashed', padding: 30, alignItems: 'center', marginBottom: 18 },
  uploading: { alignItems: 'center', paddingVertical: 12 },
  uploadingTitle: { color: '#fff', fontSize: 18, fontWeight: '700', marginTop: 14, marginBottom: 6 },
  uploadingProg: { color: 'rgba(255,255,255,0.4)', fontSize: 13, marginBottom: 18 },
  uploadingBarBg: { width: 180, height: 3, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 2 },
  uploadingBarFill: { width: '65%', height: 3, backgroundColor: '#4F8AFF', borderRadius: 2 },
  uploadIconWrap: { width: 72, height: 72, borderRadius: 22, backgroundColor: 'rgba(79,138,255,0.12)', alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  uploadIcon: { fontSize: 32 },
  uploadTitle: { color: '#fff', fontSize: 18, fontWeight: '800', marginBottom: 8, textAlign: 'center' },
  uploadSub: { color: 'rgba(255,255,255,0.38)', fontSize: 13, textAlign: 'center', lineHeight: 20, marginBottom: 24, paddingHorizontal: 8 },
  uploadBtns: { flexDirection: 'row', gap: 10, marginBottom: 12 },
  btnPrimary: { backgroundColor: '#4F8AFF', borderRadius: 14, paddingVertical: 13, paddingHorizontal: 22 },
  btnPrimaryText: { color: '#fff', fontSize: 14, fontWeight: '700' },
  btnSecondary: { backgroundColor: 'rgba(255,255,255,0.07)', borderRadius: 14, paddingVertical: 13, paddingHorizontal: 22, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)' },
  btnSecondaryText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  uploadHint: { color: 'rgba(255,255,255,0.22)', fontSize: 11 },
  statsRow: { flexDirection: 'row', paddingHorizontal: 20, gap: 10, marginBottom: 16 },
  statCard: { flex: 1, backgroundColor: '#0D1426', borderRadius: 16, padding: 14, alignItems: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  statIcon: { fontSize: 20, marginBottom: 6 },
  statVal: { color: '#fff', fontSize: 18, fontWeight: '900', letterSpacing: -0.5 },
  statLbl: { color: 'rgba(255,255,255,0.3)', fontSize: 10, marginTop: 3, textAlign: 'center' },
  searchCard: { marginHorizontal: 20, backgroundColor: '#0D1426', borderRadius: 18, padding: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 22, borderWidth: 1, borderColor: 'rgba(79,138,255,0.15)' },
  searchCardLeft: { flexDirection: 'row', alignItems: 'center', gap: 14, flex: 1 },
  searchCardIcon: { fontSize: 28, width: 44, height: 44, textAlign: 'center', lineHeight: 44, backgroundColor: 'rgba(79,138,255,0.1)', borderRadius: 12 },
  searchCardTitle: { color: '#fff', fontSize: 15, fontWeight: '700' },
  searchCardSub: { color: 'rgba(255,255,255,0.35)', fontSize: 12, marginTop: 2 },
  searchCardArrow: { color: '#4F8AFF', fontSize: 22, fontWeight: '700' },
  recentSection: { paddingHorizontal: 20 },
  recentHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  recentTitle: { color: '#fff', fontSize: 18, fontWeight: '800' },
  recentViewAll: { color: '#4F8AFF', fontSize: 13, fontWeight: '600' },
  recentCard: { backgroundColor: '#0D1426', borderRadius: 16, padding: 16, marginBottom: 10, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  recentLeft: { flexDirection: 'row', alignItems: 'center', gap: 10, flex: 1 },
  dot: { width: 8, height: 8, borderRadius: 4, flexShrink: 0 },
  recentName: { color: '#fff', fontSize: 14, fontWeight: '600', marginBottom: 2 },
  recentMeta: { color: 'rgba(255,255,255,0.3)', fontSize: 11 },
  recentScore: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6, marginLeft: 8 },
  recentScoreText: { fontSize: 17, fontWeight: '900' },
});
