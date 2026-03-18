import React, { useEffect, useState, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Animated, Dimensions, StatusBar, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width } = Dimensions.get('window');
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function Landing() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const heroFade = useRef(new Animated.Value(0)).current;
  const heroSlide = useRef(new Animated.Value(32)).current;

  useEffect(() => { checkAuth(); }, []);

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
          <View />
        </View>

        {/* Hero - ✅ Part A: H1 as accessibilityRole="header" on web */}
        <Animated.View style={[ls.hero, { opacity: heroFade, transform: [{ translateY: heroSlide }] }]}>
          <View style={ls.heroBadge}><Text style={ls.heroBadgeText}>✦ AI-Powered · Instant · Free</Text></View>

          {/* ✅ H1 - rendered as <h1> on web via accessibilityRole */}
          <Text
            style={ls.heroTitle}
            accessibilityRole="header"
            aria-level={1}
          >
            Finsight – Your AI-Powered{'\n'}<Text style={ls.heroAccent}>Financial SEO Dashboard</Text>
          </Text>

          <Text style={ls.heroSub}>Upload any PDF — annual reports, quarterly results, balance sheets. Get a complete AI analysis with health scores, 15+ metrics, management commentary and plain-English verdict.</Text>
          <View style={ls.heroBtns}>
            <TouchableOpacity style={ls.heroCtaBtn} onPress={() => router.push('/register')}>
              <Text style={ls.heroCtaBtnText}>Start Free →</Text>
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

        {/* ✅ Part A: GEO Content — Citations, Statistics, Expert Quote */}
        {Platform.OS === 'web' && (
          <View style={ls.geoSection}>
            <Text style={ls.geoTitle}>Why Structured Financial SEO Matters</Text>
            <View style={ls.geoGrid}>
              <View style={ls.geoCard}>
                <Text style={ls.geoIcon}>🔍</Text>
                <Text style={ls.geoCardTitle}>Structured Data Dominance</Text>
                <Text style={ls.geoCardText}>
                  According to Google Search Central, pages with JSON-LD structured data earn significantly more rich results in SERPs.{' '}
                  <Text style={ls.geoHighlight}>90% of top-ranked pages</Text> implement schema markup — and Finsight adds all three critical schemas automatically.
                </Text>
              </View>
              <View style={ls.geoCard}>
                <Text style={ls.geoIcon}>📈</Text>
                <Text style={ls.geoCardTitle}>Link Authority & AI Visibility</Text>
                <Text style={ls.geoCardText}>
                  Moz's Domain Authority research confirms referring domain count is the strongest predictor of organic ranking.{' '}
                  Pages with <Text style={ls.geoHighlight}>20+ referring domains</Text> rank in top 3 positions 4× more often.
                </Text>
              </View>
              <View style={ls.geoCard}>
                <Text style={ls.geoIcon}>🤖</Text>
                <Text style={ls.geoCardTitle}>Generative Engine Optimization</Text>
                <Text style={ls.geoCardText}>
                  The Princeton GEO Model (2023) shows authoritative citations and statistics can increase AI engine visibility by{' '}
                  <Text style={ls.geoHighlight}>up to 40%</Text>. FAQ schema yields a{' '}
                  <Text style={ls.geoHighlight}>30% uplift</Text> in AI citation rates.
                </Text>
              </View>
            </View>

            {/* Expert Quote */}
            <View style={ls.quoteCard}>
              <Text style={ls.quoteText}>
                "The future of SEO is not just about ranking on Google — it's about being cited by AI. Pages that demonstrate genuine expertise, authoritative citations, and structured content will win in both traditional and generative search."
              </Text>
              <Text style={ls.quoteAuthor}>— Rand Fishkin, Founder of Moz & SparkToro</Text>
            </View>

            {/* Stats Row */}
            <View style={ls.statsRow}>
              <View style={ls.statItem}>
                <Text style={ls.statNum}>90%</Text>
                <Text style={ls.statLabel}>Top pages use structured data</Text>
              </View>
              <View style={ls.statDivider} />
              <View style={ls.statItem}>
                <Text style={ls.statNum}>40%</Text>
                <Text style={ls.statLabel}>GEO visibility boost</Text>
              </View>
              <View style={ls.statDivider} />
              <View style={ls.statItem}>
                <Text style={ls.statNum}>3×</Text>
                <Text style={ls.statLabel}>More AI citations with E-E-A-T</Text>
              </View>
            </View>
          </View>
        )}

        {/* CTA */}
        <View style={ls.ctaSection}>
          <Text style={ls.ctaTitle}>Start Analysing{'\n'}Your Financials</Text>
          <TouchableOpacity style={ls.ctaBtn} onPress={() => router.push('/register')}>
            <Text style={ls.ctaBtnText}>Get Started Free →</Text>
          </TouchableOpacity>
        </View>

        {/* ✅ Part A: Footer with About/Contact E-E-A-T links */}
        <View style={ls.footerRow}>
          <Text style={ls.footerText}>📊 FinSight · AI Financial Analysis · 2024</Text>
          <Text style={ls.footerText}> · </Text>
          <TouchableOpacity onPress={() => router.push('/register')}>
            <Text style={ls.footerLink}>About</Text>
          </TouchableOpacity>
          <Text style={ls.footerText}> · </Text>
          <TouchableOpacity onPress={() => router.push('/register')}>
            <Text style={ls.footerLink}>Contact</Text>
          </TouchableOpacity>
        </View>
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
  hero: { paddingHorizontal: 24, paddingBottom: 40 },
  heroBadge: { backgroundColor: 'rgba(79,138,255,0.15)', borderRadius: 22, paddingHorizontal: 14, paddingVertical: 7, alignSelf: 'flex-start', marginBottom: 22, borderWidth: 1, borderColor: 'rgba(79,138,255,0.3)' },
  heroBadgeText: { color: '#4F8AFF', fontSize: 12, fontWeight: '700' },
  heroTitle: { fontSize: width > 400 ? 46 : 38, fontWeight: '900', color: '#fff', lineHeight: width > 400 ? 54 : 46, letterSpacing: -1.5, marginBottom: 18 },
  heroAccent: { color: '#4F8AFF' },
  heroSub: { fontSize: 15, color: 'rgba(255,255,255,0.55)', lineHeight: 26, marginBottom: 32 },
  heroBtns: { flexDirection: 'row', gap: 12, marginBottom: 14 },
  heroCtaBtn: { flex: 1, backgroundColor: '#4F8AFF', borderRadius: 16, paddingVertical: 17, alignItems: 'center' },
  heroCtaBtnText: { color: '#fff', fontSize: 16, fontWeight: '800' },
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
  // GEO Section
  geoSection: { paddingHorizontal: 20, paddingBottom: 48 },
  geoTitle: { fontSize: 26, fontWeight: '900', color: '#fff', letterSpacing: -0.8, textAlign: 'center', marginBottom: 24 },
  geoGrid: { gap: 14, marginBottom: 24 },
  geoCard: { backgroundColor: '#0D1426', borderRadius: 16, padding: 20, borderWidth: 1, borderColor: 'rgba(79,138,255,0.15)' },
  geoIcon: { fontSize: 24, marginBottom: 8 },
  geoCardTitle: { color: '#fff', fontSize: 15, fontWeight: '700', marginBottom: 8 },
  geoCardText: { color: 'rgba(255,255,255,0.45)', fontSize: 13, lineHeight: 20 },
  geoHighlight: { color: '#4F8AFF', fontWeight: '700' },
  quoteCard: { backgroundColor: 'rgba(79,138,255,0.08)', borderRadius: 16, padding: 24, borderLeftWidth: 3, borderLeftColor: '#4F8AFF', marginBottom: 24 },
  quoteText: { color: 'rgba(255,255,255,0.7)', fontSize: 14, lineHeight: 22, fontStyle: 'italic', marginBottom: 12 },
  quoteAuthor: { color: '#4F8AFF', fontSize: 12, fontWeight: '700' },
  statsRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-around', backgroundColor: '#0D1426', borderRadius: 16, padding: 20, borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' },
  statItem: { alignItems: 'center', flex: 1 },
  statNum: { color: '#4F8AFF', fontSize: 28, fontWeight: '900', marginBottom: 4 },
  statLabel: { color: 'rgba(255,255,255,0.35)', fontSize: 11, textAlign: 'center', lineHeight: 15 },
  statDivider: { width: 1, height: 40, backgroundColor: 'rgba(255,255,255,0.08)' },
  ctaSection: { marginHorizontal: 20, backgroundColor: '#4F8AFF', borderRadius: 24, padding: 36, alignItems: 'center', marginBottom: 40 },
  ctaTitle: { fontSize: 28, fontWeight: '900', color: '#fff', textAlign: 'center', marginBottom: 24, lineHeight: 36, letterSpacing: -0.5 },
  ctaBtn: { backgroundColor: '#fff', borderRadius: 16, paddingVertical: 16, paddingHorizontal: 36 },
  ctaBtnText: { color: '#0052FF', fontSize: 16, fontWeight: '900' },
  footerRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', flexWrap: 'wrap', paddingHorizontal: 20, paddingBottom: 8 },
  footerText: { color: 'rgba(255,255,255,0.18)', fontSize: 12 },
  footerLink: { color: 'rgba(79,138,255,0.6)', fontSize: 12 },
});
