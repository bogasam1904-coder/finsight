import React, { useEffect, useState, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Animated, Dimensions, StatusBar } from 'react-native';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width } = Dimensions.get('window');
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function Landing() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const heroFade = useRef(new Animated.Value(0)).current;
  const heroSlide = useRef(new Animated.Value(32)).current;

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (token) {
        const res = await fetch(`${BACKEND}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
        if (res.ok) { router.replace('/(tabs)'); return; }
        await AsyncStorage.multiRemove(['token', 'user']);
      }
    } catch { }
    setChecking(false);
    Animated.parallel([
      Animated.timing(heroFade, { toValue: 1, duration: 900, useNativeDriver: true }),
      Animated.timing(heroSlide, { toValue: 0, duration: 800, useNativeDriver: true }),
    ]).start();
  };

  if (checking) return (
    <View style={ls.splash}>
      <StatusBar barStyle="light-content" />
      <Text style={ls.splashEmoji}>📊</Text>
      <Text style={ls.splashName}>FinSight</Text>
    </View>
  );

  const features = [
    { icon: '🧠', title: 'Deep AI Analysis', desc: 'Complete financial breakdown in under 30 seconds' },
    { icon: '📈', title: 'Health Score 0–100', desc: 'Instant financial strength rating with full reasoning' },
    { icon: '💡', title: 'Plain English', desc: 'Complex statements explained simply' },
    { icon: '🔗', title: 'Share Anywhere', desc: 'Public shareable links — no login needed for viewers' },
    { icon: '🌙', title: 'Dark & Light Mode', desc: 'Matches your preference. PDF saves in your active theme' },
    { icon: '📄', title: 'Download Reports', desc: 'Formatted PDF reports for any document' },
  ];

  return (
    <View style={ls.root}>
      <StatusBar barStyle="light-content" />
      <View style={ls.bgBlobs}>
        <View style={[ls.blob, { width: 420, height: 420, backgroundColor: 'rgba(79,138,255,0.13)', top: -160, right: -140 }]} />
        <View style={[ls.blob, { width: 280, height: 280, backgroundColor: 'rgba(34,197,94,0.08)', top: 380, left: -100 }]} />
        <View style={[ls.blob, { width: 500, height: 500, backgroundColor: 'rgba(79,138,255,0.06)', bottom: -200, right: -200 }]} />
      </View>
      <ScrollView showsVerticalScrollIndicator={false}>
        {/* Nav */}
        <View style={ls.nav}>
          <View style={ls.navLogo}>
            <Text style={ls.navEmoji}>📊</Text>
            <Text style={ls.navName}>FinSight</Text>
          </View>
          <TouchableOpacity style={ls.navSignIn} onPress={() => router.push('/login')}>
            <Text style={ls.navSignInText}>Sign In</Text>
          </TouchableOpacity>
        </View>

        {/* Hero */}
        <Animated.View style={[ls.hero, { opacity: heroFade, transform: [{ translateY: heroSlide }] }]}>
          <View style={ls.heroBadge}><Text style={ls.heroBadgeText}>✦ AI-Powered · Instant · Free</Text></View>
          <Text style={ls.heroTitle}>Understand Any{'\n'}<Text style={ls.heroAccent}>Financial Report</Text>{'\n'}In Seconds</Text>
          <Text style={ls.heroSub}>Upload any PDF — annual reports, quarterly results, balance sheets. Get a complete AI analysis with health scores, 15+ metrics, management commentary and plain-English verdict.</Text>
          <View style={ls.heroBtns}>
            <TouchableOpacity style={ls.heroCtaBtn} onPress={() => router.push('/register')}>
              <Text style={ls.heroCtaBtnText}>Start Free →</Text>
            </TouchableOpacity>
            <TouchableOpacity style={ls.heroGhostBtn} onPress={() => router.push('/login')}>
              <Text style={ls.heroGhostBtnText}>Sign In</Text>
            </TouchableOpacity>
          </View>
          <Text style={ls.heroNote}>No credit card · Free to use</Text>
        </Animated.View>

        {/* Mock screen */}
        <Animated.View style={[ls.mockCard, { opacity: heroFade }]}>
          <View style={ls.mockBar}>
            <View style={ls.mockDots}>
              {['#FF5F57','#FEBC2E','#28C840'].map((c,i) => <View key={i} style={[ls.mockDot, { backgroundColor: c }]} />)}
            </View>
            <Text style={ls.mockBarTitle}>FinSight · Analysis</Text>
          </View>
          <View style={ls.mockBody}>
            <View style={ls.mockTop}>
              <View>
                <Text style={ls.mockCompany}>Reliance Industries Ltd</Text>
                <Text style={ls.mockPeriod}>Q3 FY2024 · INR Crores</Text>
              </View>
              <View style={ls.mockScore}>
                <Text style={ls.mockScoreNum}>82</Text>
                <Text style={ls.mockScoreLabel}>GOOD</Text>
              </View>
            </View>
            <View style={ls.mockMetrics}>
              {[
                { l:'Revenue', v:'₹2,31,820 Cr', c:'+6.2%', up:true },
                { l:'Net Profit', v:'₹17,265 Cr', c:'+12.4%', up:true },
                { l:'EBITDA Margin', v:'16.2%', c:'+0.8%', up:true },
                { l:'D/E Ratio', v:'0.38x', c:'-0.04', up:false },
              ].map((m,i) => (
                <View key={i} style={ls.mockMetric}>
                  <Text style={ls.mockMetricLabel}>{m.l}</Text>
                  <Text style={ls.mockMetricVal}>{m.v}</Text>
                  <Text style={[ls.mockMetricChg, { color: m.up ? '#22c55e' : '#ef4444' }]}>{m.up?'↑':'↓'} {m.c}</Text>
                </View>
              ))}
            </View>
            <View style={ls.mockVerdict}>
              <Text style={ls.mockVerdictLabel}>💡 Plain English</Text>
              <Text style={ls.mockVerdictText}>Reliance continues to deliver solid growth driven by Jio and Retail segments. Balance sheet remains healthy with manageable debt...</Text>
            </View>
          </View>
        </Animated.View>

        {/* Features */}
        <View style={ls.section}>
          <Text style={ls.sectionTitle}>Everything You Need</Text>
          <Text style={ls.sectionSub}>Professional financial analysis, built for everyone</Text>
          <View style={ls.grid}>
            {features.map((f,i) => (
              <View key={i} style={ls.featureCard}>
                <Text style={ls.featureIcon}>{f.icon}</Text>
                <Text style={ls.featureTitle}>{f.title}</Text>
                <Text style={ls.featureDesc}>{f.desc}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* CTA */}
        <View style={ls.ctaSection}>
          <Text style={ls.ctaTitle}>Start Analysing{'\n'}Your Financials</Text>
          <TouchableOpacity style={ls.ctaBtn} onPress={() => router.push('/register')}>
            <Text style={ls.ctaBtnText}>Get Started Free →</Text>
          </TouchableOpacity>
        </View>
        <Text style={ls.footer}>📊 FinSight · AI Financial Analysis · 2024</Text>
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const ls = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#030B1A' },
  splash: { flex: 1, backgroundColor: '#030B1A', justifyContent: 'center', alignItems: 'center' },
  splashEmoji: { fontSize: 60, marginBottom: 12 },
  splashName: { fontSize: 34, fontWeight: '900', color: '#4F8AFF', letterSpacing: -1 },
  bgBlobs: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, overflow: 'hidden' },
  blob: { position: 'absolute', borderRadius: 999 },
  nav: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 24, paddingTop: 58, paddingBottom: 24 },
  navLogo: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  navEmoji: { fontSize: 26 },
  navName: { fontSize: 22, fontWeight: '900', color: '#fff', letterSpacing: -0.5 },
  navSignIn: { backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 22, paddingHorizontal: 18, paddingVertical: 9, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)' },
  navSignInText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  hero: { paddingHorizontal: 24, paddingBottom: 40 },
  heroBadge: { backgroundColor: 'rgba(79,138,255,0.15)', borderRadius: 22, paddingHorizontal: 14, paddingVertical: 7, alignSelf: 'flex-start', marginBottom: 22, borderWidth: 1, borderColor: 'rgba(79,138,255,0.3)' },
  heroBadgeText: { color: '#4F8AFF', fontSize: 12, fontWeight: '700' },
  heroTitle: { fontSize: width > 400 ? 46 : 38, fontWeight: '900', color: '#fff', lineHeight: width > 400 ? 54 : 46, letterSpacing: -1.5, marginBottom: 18 },
  heroAccent: { color: '#4F8AFF' },
  heroSub: { fontSize: 15, color: 'rgba(255,255,255,0.55)', lineHeight: 26, marginBottom: 32 },
  heroBtns: { flexDirection: 'row', gap: 12, marginBottom: 14 },
  heroCtaBtn: { flex: 1, backgroundColor: '#4F8AFF', borderRadius: 16, paddingVertical: 17, alignItems: 'center' },
  heroCtaBtnText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  heroGhostBtn: { backgroundColor: 'rgba(255,255,255,0.07)', borderRadius: 16, paddingVertical: 17, paddingHorizontal: 26, borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)' },
  heroGhostBtnText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  heroNote: { color: 'rgba(255,255,255,0.25)', fontSize: 12, textAlign: 'center' },
  mockCard: { marginHorizontal: 20, borderRadius: 22, backgroundColor: '#0D1426', borderWidth: 1, borderColor: 'rgba(79,138,255,0.2)', overflow: 'hidden', marginBottom: 60 },
  mockBar: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.05)', gap: 12 },
  mockDots: { flexDirection: 'row', gap: 6 },
  mockDot: { width: 10, height: 10, borderRadius: 5 },
  mockBarTitle: { color: 'rgba(255,255,255,0.3)', fontSize: 12, fontWeight: '600' },
  mockBody: { padding: 18 },
  mockTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 },
  mockCompany: { color: '#fff', fontSize: 17, fontWeight: '800', marginBottom: 3 },
  mockPeriod: { color: 'rgba(255,255,255,0.35)', fontSize: 12 },
  mockScore: { backgroundColor: 'rgba(34,197,94,0.15)', borderRadius: 14, paddingHorizontal: 14, paddingVertical: 10, alignItems: 'center', borderWidth: 1, borderColor: 'rgba(34,197,94,0.25)' },
  mockScoreNum: { color: '#22c55e', fontSize: 26, fontWeight: '900', lineHeight: 30 },
  mockScoreLabel: { color: '#22c55e', fontSize: 9, fontWeight: '800', letterSpacing: 1 },
  mockMetrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 },
  mockMetric: { backgroundColor: 'rgba(255,255,255,0.04)', borderRadius: 12, padding: 12, minWidth: '46%', flex: 1, borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  mockMetricLabel: { color: 'rgba(255,255,255,0.35)', fontSize: 10, marginBottom: 4 },
  mockMetricVal: { color: '#fff', fontSize: 14, fontWeight: '700', marginBottom: 2 },
  mockMetricChg: { fontSize: 11, fontWeight: '700' },
  mockVerdict: { backgroundColor: 'rgba(79,138,255,0.08)', borderRadius: 12, padding: 14, borderLeftWidth: 3, borderLeftColor: '#4F8AFF' },
  mockVerdictLabel: { color: '#4F8AFF', fontSize: 11, fontWeight: '700', marginBottom: 6 },
  mockVerdictText: { color: 'rgba(255,255,255,0.55)', fontSize: 12, lineHeight: 18 },
  section: { paddingHorizontal: 20, paddingBottom: 56 },
  sectionTitle: { fontSize: 30, fontWeight: '900', color: '#fff', letterSpacing: -1, textAlign: 'center', marginBottom: 8 },
  sectionSub: { color: 'rgba(255,255,255,0.35)', fontSize: 14, textAlign: 'center', marginBottom: 28 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  featureCard: { backgroundColor: '#0D1426', borderRadius: 18, padding: 20, width: (width - 52) / 2, borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' },
  featureIcon: { fontSize: 28, marginBottom: 10 },
  featureTitle: { color: '#fff', fontSize: 14, fontWeight: '700', marginBottom: 6 },
  featureDesc: { color: 'rgba(255,255,255,0.35)', fontSize: 12, lineHeight: 18 },
  ctaSection: { marginHorizontal: 20, backgroundColor: '#4F8AFF', borderRadius: 24, padding: 36, alignItems: 'center', marginBottom: 40 },
  ctaTitle: { fontSize: 28, fontWeight: '900', color: '#fff', textAlign: 'center', marginBottom: 24, lineHeight: 36, letterSpacing: -0.5 },
  ctaBtn: { backgroundColor: '#fff', borderRadius: 16, paddingVertical: 16, paddingHorizontal: 36 },
  ctaBtnText: { color: '#0052FF', fontSize: 16, fontWeight: '900' },
  footer: { textAlign: 'center', color: 'rgba(255,255,255,0.18)', fontSize: 12 },
});
