import React, { useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Switch, Share, Platform, Alert, Linking, StatusBar
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const T = {
  light: { bg: '#F4F7FF', card: '#FFFFFF', cardAlt: '#F0F4FF', text: '#0A0E1A', textSub: '#6B7280', border: '#E5E7EB', accent: '#0052FF', accentBg: '#EEF4FF' },
  dark:  { bg: '#060B18', card: '#0D1426', cardAlt: '#111B35', text: '#F0F4FF', textSub: '#6B82A8', border: '#1E2D4A', accent: '#4F8AFF', accentBg: '#0D1D3A' },
};

export default function ShareScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(true);
  const [copied, setCopied] = useState(false);
  const t = dark ? T.dark : T.light;

  useEffect(() => { fetchAnalysis(); }, [id]);

  const fetchAnalysis = async () => {
    try {
      // PUBLIC endpoint — no token needed
      const res = await fetch(`${BACKEND}/api/public/analyses/${id}`);
      if (!res.ok) throw new Error('Not found');
      const data = await res.json();
      setAnalysis(data);
    } catch {
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  };

  const shareUrl = `https://finsight-vert.vercel.app/share/${id}`;

  const handleCopy = async () => {
    try {
      if (Platform.OS === 'web' && navigator?.clipboard) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        await Share.share({ message: shareUrl });
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch { }
  };

  const handleWhatsApp = async () => {
    const r = analysis?.result;
    const msg = `📊 ${r?.company_name} Financial Analysis\n\nHealth Score: ${r?.health_score}/100 (${r?.health_label})\n\n${r?.investor_verdict?.substring(0, 150)}...\n\nFull analysis: ${shareUrl}`;
    const url = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { await Linking.openURL(url); }
  };

  const handleTwitter = async () => {
    const r = analysis?.result;
    const text = `📊 ${r?.company_name} — Health Score: ${r?.health_score}/100 (${r?.health_label}) via FinSight`;
    const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(shareUrl)}`;
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { await Linking.openURL(url); }
  };

  if (loading) return (
    <View style={[cs.center, { backgroundColor: '#060B18' }]}>
      <StatusBar barStyle="light-content" />
      <ActivityIndicator size="large" color="#4F8AFF" />
      <Text style={{ color: '#6B82A8', marginTop: 14, fontSize: 15 }}>Loading analysis...</Text>
    </View>
  );

  if (!analysis?.result) return (
    <View style={[cs.center, { backgroundColor: '#060B18' }]}>
      <StatusBar barStyle="light-content" />
      <Text style={{ fontSize: 56, marginBottom: 16 }}>📊</Text>
      <Text style={{ color: '#F0F4FF', fontSize: 22, fontWeight: '800', marginBottom: 8 }}>Analysis Not Found</Text>
      <Text style={{ color: '#6B82A8', fontSize: 14, textAlign: 'center', lineHeight: 22, marginBottom: 28, paddingHorizontal: 24 }}>
        This link may be expired or incorrect.
      </Text>
      <TouchableOpacity style={cs.ctaBtn} onPress={() => router.replace('/')}>
        <Text style={cs.ctaBtnText}>Try FinSight Free →</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';

  const Card = ({ title, children, leftBorder }: any) => (
    <View style={[cs.card, { backgroundColor: t.card, borderColor: t.border, borderLeftColor: leftBorder || t.border, borderLeftWidth: leftBorder ? 3 : 1 }]}>
      {title && <Text style={[cs.cardTitle, { color: t.text }]}>{title}</Text>}
      {children}
    </View>
  );

  const MetricRow = ({ m }: any) => {
    if (!m.current || m.current === 'N/A') return null;
    const tc = m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : t.textSub;
    const ti = m.trend === 'up' ? '▲' : m.trend === 'down' ? '▼' : '—';
    return (
      <View style={[cs.metricRow, { borderBottomColor: t.border }]}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <Text style={[cs.metricLabel, { color: t.text }]}>{m.label}</Text>
          {m.comment && m.comment !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2, fontStyle: 'italic' }}>{m.comment}</Text>}
        </View>
        <View style={{ alignItems: 'flex-end', minWidth: 100 }}>
          <Text style={{ fontSize: 14, fontWeight: '800', color: t.text }}>{m.current}</Text>
          {m.previous && m.previous !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2 }}>vs {m.previous}</Text>}
          {m.change && m.change !== 'N/A' && <Text style={{ fontSize: 12, color: tc, fontWeight: '700', marginTop: 2 }}>{ti} {m.change}</Text>}
        </View>
      </View>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ScrollView showsVerticalScrollIndicator={false}>

        {/* Top bar */}
        <View style={[cs.topBar, { borderBottomColor: t.border }]}>
          <View style={cs.logoRow}>
            <Text style={{ fontSize: 22 }}>📊</Text>
            <Text style={[cs.logoText, { color: t.accent }]}>FinSight</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Text style={{ fontSize: 14 }}>{dark ? '🌙' : '☀️'}</Text>
            <Switch value={dark} onValueChange={setDark}
              trackColor={{ false: '#CBD5E1', true: t.accent }}
              thumbColor="#fff" style={{ transform: [{ scale: 0.8 }] }} />
          </View>
        </View>

        {/* Shared via badge */}
        <View style={[cs.sharedBadge, { backgroundColor: t.accentBg }]}>
          <Text style={[cs.sharedBadgeText, { color: t.accent }]}>📤 Shared via FinSight — AI Financial Analysis</Text>
        </View>

        <View style={{ paddingHorizontal: 16 }}>

          {/* Header */}
          <View style={cs.header}>
            <Text style={[cs.company, { color: t.text }]}>{r.company_name}</Text>
            <Text style={[cs.period, { color: t.textSub }]}>{r.statement_type} · {r.period} · {r.currency}</Text>
          </View>

          {/* Score */}
          <View style={[cs.scoreCard, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={[cs.scoreCardLabel, { color: t.textSub }]}>FINANCIAL HEALTH SCORE</Text>
            <View style={{ flexDirection: 'row', alignItems: 'flex-end' }}>
              <Text style={[cs.scoreNum, { color: scoreColor }]}>{r.health_score}</Text>
              <Text style={{ fontSize: 26, fontWeight: '600', color: t.textSub, marginBottom: 14 }}>/100</Text>
            </View>
            <View style={[cs.scoreLabelPill, { backgroundColor: scoreColor + '20' }]}>
              <Text style={{ color: scoreColor, fontSize: 16, fontWeight: '800' }}>{r.health_label}</Text>
            </View>
          </View>

          {r.executive_summary && (
            <Card title="📋 Executive Summary">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.executive_summary}</Text>
            </Card>
          )}

          {r.investor_verdict && (
            <Card title="💡 Plain English Verdict" leftBorder={t.accent}>
              <View style={[cs.verdictBox, { backgroundColor: t.accentBg }]}>
                <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.investor_verdict}</Text>
              </View>
            </Card>
          )}

          {r.key_metrics?.filter((m: any) => m.current && m.current !== 'N/A').length > 0 && (
            <Card title="📊 Key Metrics">
              <View style={[cs.metricsHead, { borderBottomColor: t.border }]}>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Metric</Text>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Now · Before · Δ</Text>
              </View>
              {r.key_metrics.map((m: any, i: number) => <MetricRow key={i} m={m} />)}
            </Card>
          )}

          {r.highlights?.length > 0 && (
            <Card title="✅ Key Strengths">
              {r.highlights.map((h: string, i: number) => (
                <View key={i} style={cs.dotRow}>
                  <View style={[cs.dot, { backgroundColor: '#22c55e25' }]}><Text style={{ color: '#22c55e', fontSize: 10, fontWeight: '800' }}>✓</Text></View>
                  <Text style={{ fontSize: 14, lineHeight: 22, flex: 1, color: t.text }}>{h}</Text>
                </View>
              ))}
            </Card>
          )}

          {r.risks?.length > 0 && (
            <Card title="⚠️ Key Risks">
              {r.risks.map((risk: string, i: number) => (
                <View key={i} style={cs.dotRow}>
                  <View style={[cs.dot, { backgroundColor: '#ef444425' }]}><Text style={{ color: '#ef4444', fontSize: 10, fontWeight: '800' }}>!</Text></View>
                  <Text style={{ fontSize: 14, lineHeight: 22, flex: 1, color: t.text }}>{risk}</Text>
                </View>
              ))}
            </Card>
          )}

          {/* Share section */}
          <View style={[cs.sharePanel, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={[cs.sharePanelTitle, { color: t.textSub }]}>SHARE THIS ANALYSIS</Text>
            <TouchableOpacity
              style={[cs.copyBtn, { borderColor: copied ? '#22c55e' : t.accent, backgroundColor: copied ? '#22c55e15' : t.accentBg }]}
              onPress={handleCopy}
            >
              <Text style={{ color: copied ? '#22c55e' : t.accent, fontSize: 15, fontWeight: '700' }}>
                {copied ? '✅ Copied!' : '🔗 Copy Link'}
              </Text>
            </TouchableOpacity>
            <View style={{ flexDirection: 'row', gap: 10 }}>
              <TouchableOpacity style={[cs.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleWhatsApp}>
                <Text style={cs.shareBtnText}>💬 WhatsApp</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[cs.shareBtn, { backgroundColor: '#000' }]} onPress={handleTwitter}>
                <Text style={cs.shareBtnText}>𝕏 Twitter</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* CTA */}
          <View style={[cs.cta, { backgroundColor: t.accent }]}>
            <Text style={cs.ctaTitle}>📊 Analyse Your Own Documents</Text>
            <Text style={cs.ctaSub}>Upload any financial PDF and get AI-powered analysis in seconds — free</Text>
            <TouchableOpacity style={cs.ctaBtn} onPress={() => router.replace('/')}>
              <Text style={cs.ctaBtnText}>Try FinSight Free →</Text>
            </TouchableOpacity>
          </View>

          <View style={{ height: 60 }} />
        </View>
      </ScrollView>
    </View>
  );
}

const cs = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 56, paddingBottom: 16, borderBottomWidth: 1 },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  logoText: { fontSize: 20, fontWeight: '900', letterSpacing: -0.5 },
  sharedBadge: { paddingHorizontal: 16, paddingVertical: 10, alignItems: 'center' },
  sharedBadgeText: { fontSize: 12, fontWeight: '600' },
  header: { paddingTop: 16, paddingBottom: 16 },
  company: { fontSize: 24, fontWeight: '900', letterSpacing: -0.8 },
  period: { fontSize: 13, marginTop: 4 },
  scoreCard: { borderRadius: 22, padding: 24, alignItems: 'center', marginBottom: 14, borderWidth: 1 },
  scoreCardLabel: { fontSize: 10, fontWeight: '700', letterSpacing: 2, textTransform: 'uppercase', marginBottom: 10 },
  scoreNum: { fontSize: 80, fontWeight: '900', lineHeight: 88, letterSpacing: -4 },
  scoreLabelPill: { borderRadius: 24, paddingHorizontal: 22, paddingVertical: 7, marginTop: 6 },
  card: { borderRadius: 20, padding: 18, marginBottom: 14, borderWidth: 1 },
  cardTitle: { fontSize: 15, fontWeight: '800', marginBottom: 14 },
  verdictBox: { borderRadius: 12, padding: 16 },
  metricsHead: { flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 10, borderBottomWidth: 1, marginBottom: 4 },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 11, borderBottomWidth: 1 },
  metricLabel: { fontSize: 13, fontWeight: '600' },
  dotRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 12 },
  dot: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1, flexShrink: 0 },
  sharePanel: { borderRadius: 22, padding: 20, marginBottom: 14, borderWidth: 1 },
  sharePanelTitle: { fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', textAlign: 'center', marginBottom: 16 },
  copyBtn: { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1.5, marginBottom: 12 },
  shareBtn: { flex: 1, borderRadius: 14, padding: 14, alignItems: 'center' },
  shareBtnText: { color: '#fff', fontSize: 13, fontWeight: '700' },
  cta: { borderRadius: 22, padding: 28, alignItems: 'center', marginBottom: 14 },
  ctaTitle: { color: '#fff', fontSize: 18, fontWeight: '900', textAlign: 'center', marginBottom: 8, letterSpacing: -0.3 },
  ctaSub: { color: 'rgba(255,255,255,0.8)', fontSize: 13, textAlign: 'center', marginBottom: 20, lineHeight: 20 },
  ctaBtn: { backgroundColor: '#fff', borderRadius: 14, paddingVertical: 14, paddingHorizontal: 28 },
  ctaBtnText: { color: '#0052FF', fontSize: 15, fontWeight: '800' },
});
