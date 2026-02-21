import React, { useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Switch, Platform, Alert, Linking, Share
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const lightTheme = {
  bg: '#F0F4FF', card: '#FFFFFF', cardAlt: '#F8FAFF',
  text: '#0A0E1A', textSecondary: '#6B7280', border: '#E5E7EB',
  accent: '#0052FF', accentLight: '#EEF4FF',
};
const darkTheme = {
  bg: '#0A0E1A', card: '#141826', cardAlt: '#1C2233',
  text: '#F1F5F9', textSecondary: '#94A3B8', border: '#2D3748',
  accent: '#4F8AFF', accentLight: '#1A2540',
};

const ScoreBreakdown = ({ breakdown, t }: any) => {
  if (!breakdown?.components) return null;
  const colors: Record<string, string> = { 'Strong': '#22c55e', 'Moderate': '#f59e0b', 'Weak': '#ef4444' };
  return (
    <View style={{ marginTop: 16, width: '100%' }}>
      <Text style={[styles.subTitle, { color: t.text, marginBottom: 8 }]}>Score Breakdown:</Text>
      {breakdown.components.map((c: any, i: number) => {
        const pct = c.max > 0 ? (c.score / c.max) * 100 : 0;
        const barColor = colors[c.rating] || '#888';
        return (
          <View key={i} style={[styles.scoreComponentBox, { backgroundColor: t.cardAlt }]}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <Text style={{ fontSize: 13, fontWeight: '700', color: t.text }}>{c.category}</Text>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <View style={[styles.ratingBadge, { backgroundColor: barColor + '20' }]}>
                  <Text style={{ fontSize: 10, color: barColor, fontWeight: '700' }}>{c.rating}</Text>
                </View>
                <Text style={{ fontSize: 13, fontWeight: '700', color: barColor }}>{c.score}/{c.max}</Text>
              </View>
            </View>
            <View style={[styles.progressBarBg, { backgroundColor: t.border }]}>
              <View style={[styles.progressBarFill, { width: `${pct}%` as any, backgroundColor: barColor }]} />
            </View>
            <Text style={{ fontSize: 12, color: t.textSecondary, marginTop: 6, lineHeight: 18 }}>{c.reasoning}</Text>
          </View>
        );
      })}
    </View>
  );
};

export default function PublicAnalysisScreen() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const t = dark ? darkTheme : lightTheme;

  useEffect(() => { fetchAnalysis(); }, [id]);

  const fetchAnalysis = async () => {
    try {
      // PUBLIC endpoint — no auth needed
      const res = await fetch(`${BACKEND}/api/public/analyses/${id}`);
      if (!res.ok) throw new Error('Not found');
      const data = await res.json();
      setAnalysis(data);
    } catch (e) {
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  };

  const shareLink = `https://finsight-vert.vercel.app/share/${id}`;

  const handleCopyLink = async () => {
    try {
      if (Platform.OS === 'web' && (navigator as any)?.clipboard) {
        await (navigator as any).clipboard.writeText(shareLink);
        setLinkCopied(true);
        setTimeout(() => setLinkCopied(false), 3000);
      } else {
        await Share.share({ message: shareLink });
      }
    } catch { }
  };

  const handleShareWhatsApp = async () => {
    const r = analysis?.result;
    const msg = encodeURIComponent(`📊 FinSight Analysis: ${r?.company_name}\n\nHealth Score: ${r?.health_score}/100 (${r?.health_label})\n\nView full analysis: ${shareLink}`);
    const url = Platform.OS === 'web' ? `https://wa.me/?text=${msg}` : `whatsapp://send?text=${msg}`;
    if (Platform.OS === 'web') { window.open(`https://wa.me/?text=${msg}`, '_blank'); }
    else { await Linking.openURL(url).catch(() => Linking.openURL(`https://wa.me/?text=${msg}`)); }
  };

  const handleShareTwitter = async () => {
    const r = analysis?.result;
    const text = encodeURIComponent(`📊 ${r?.company_name} — Financial Health Score: ${r?.health_score}/100 (${r?.health_label})\n\nAnalyzed by FinSight`);
    const url = `https://twitter.com/intent/tweet?text=${text}&url=${encodeURIComponent(shareLink)}`;
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { await Linking.openURL(url); }
  };

  if (loading) return (
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={[{ color: t.textSecondary, marginTop: 12, fontSize: 16 }]}>Loading analysis...</Text>
    </View>
  );

  if (!analysis || !analysis.result) return (
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <Text style={{ fontSize: 48, marginBottom: 16 }}>📊</Text>
      <Text style={{ fontSize: 20, fontWeight: '800', color: t.text, marginBottom: 8 }}>Analysis Not Found</Text>
      <Text style={{ fontSize: 14, color: t.textSecondary, textAlign: 'center', marginBottom: 24, lineHeight: 22 }}>
        This analysis may have been deleted or the link is incorrect.
      </Text>
      <TouchableOpacity style={[styles.btn, { backgroundColor: t.accent }]} onPress={() => router.replace('/')}>
        <Text style={styles.btnText}>Go to FinSight</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : r.health_score >= 40 ? '#ef4444' : '#7f1d1d';

  const Card = ({ title, children, accent }: any) => (
    <View style={[styles.card, { backgroundColor: t.card, borderLeftColor: accent || 'transparent', borderLeftWidth: accent ? 3 : 0 }]}>
      {title && <Text style={[styles.cardTitle, { color: t.text }]}>{title}</Text>}
      {children}
    </View>
  );

  const MetricRow = ({ metric }: { metric: any }) => {
    const trendColor = metric.trend === 'up' ? '#22c55e' : metric.trend === 'down' ? '#ef4444' : '#888';
    const trendIcon = metric.trend === 'up' ? '↑' : metric.trend === 'down' ? '↓' : '→';
    return (
      <View style={[styles.metricRow, { borderBottomColor: t.border }]}>
        <View style={styles.metricLeft}>
          <Text style={[styles.metricLabel, { color: t.text }]}>{metric.label}</Text>
          {metric.comment && metric.comment !== 'N/A' && (
            <Text style={[styles.metricComment, { color: t.textSecondary }]}>{metric.comment}</Text>
          )}
        </View>
        <View style={styles.metricRight}>
          <Text style={[styles.metricCurrent, { color: t.text }]}>{metric.current}</Text>
          {metric.previous && metric.previous !== 'N/A' && (
            <Text style={[styles.metricPrevious, { color: t.textSecondary }]}>vs {metric.previous}</Text>
          )}
          {metric.change && metric.change !== 'N/A' && (
            <Text style={[styles.metricChange, { color: trendColor }]}>{trendIcon} {metric.change}</Text>
          )}
        </View>
      </View>
    );
  };

  const StatBox = ({ label, val, prev, color }: any) => {
    if (!val || val === 'N/A') return null;
    return (
      <View style={[styles.statBox, { backgroundColor: t.cardAlt }]}>
        <Text style={[styles.statValue, { color: color || t.accent }]}>{val}</Text>
        {prev && prev !== 'N/A' && <Text style={[styles.statPrev, { color: t.textSecondary }]}>vs {prev}</Text>}
        <Text style={[styles.statLabel, { color: t.textSecondary }]}>{label}</Text>
      </View>
    );
  };

  return (
    <ScrollView style={[styles.container, { backgroundColor: t.bg }]} showsVerticalScrollIndicator={false}>

      {/* Top bar */}
      <View style={styles.topBar}>
        <View style={styles.logoRow}>
          <Text style={styles.logoEmoji}>📊</Text>
          <Text style={[styles.logoText, { color: t.accent }]}>FinSight</Text>
        </View>
        <View style={styles.themeToggle}>
          <Text style={{ fontSize: 14 }}>{dark ? '🌙' : '☀️'}</Text>
          <Switch value={dark} onValueChange={setDark} trackColor={{ false: '#CBD5E1', true: '#4F8AFF' }} thumbColor='#fff' />
        </View>
      </View>

      {/* Shared by banner */}
      <View style={[styles.sharedBanner, { backgroundColor: t.accentLight }]}>
        <Text style={[styles.sharedBannerText, { color: t.accent }]}>
          📤 Shared via FinSight · AI-Powered Financial Analysis
        </Text>
      </View>

      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.company, { color: t.text }]}>{r.company_name || 'Financial Analysis'}</Text>
        <Text style={[styles.period, { color: t.textSecondary }]}>{r.statement_type} · {r.period}</Text>
        <Text style={[styles.currency, { color: t.textSecondary }]}>{r.currency}</Text>
      </View>

      {/* Health Score */}
      <View style={[styles.scoreCard, { backgroundColor: t.card }]}>
        <Text style={[styles.scoreLabel, { color: t.textSecondary }]}>FINANCIAL HEALTH SCORE</Text>
        <View style={styles.scoreCircle}>
          <Text style={[styles.score, { color: scoreColor }]}>{r.health_score}</Text>
          <Text style={[styles.scoreMax, { color: t.textSecondary }]}>/100</Text>
        </View>
        <View style={[styles.scoreBadge, { backgroundColor: scoreColor + '20' }]}>
          <Text style={[styles.scoreTag, { color: scoreColor }]}>{r.health_label}</Text>
        </View>
        <ScoreBreakdown breakdown={r.health_score_breakdown} t={t} />
      </View>

      <Card title="📋 Executive Summary">
        <Text style={[styles.bodyText, { color: t.text }]}>{r.executive_summary}</Text>
      </Card>

      {r.investor_verdict && (
        <Card title="💡 Plain English Verdict" accent={t.accent}>
          <View style={[styles.verdictBox, { backgroundColor: t.accentLight }]}>
            <Text style={[styles.bodyText, { color: t.text }]}>{r.investor_verdict}</Text>
          </View>
        </Card>
      )}

      {r.key_metrics?.length > 0 && (
        <Card title="📊 Key Financial Metrics">
          <View style={[styles.metricsHeader, { borderBottomColor: t.border }]}>
            <Text style={[styles.metricsHeaderText, { color: t.textSecondary }]}>Metric</Text>
            <Text style={[styles.metricsHeaderText, { color: t.textSecondary }]}>Current · Prev · Change</Text>
          </View>
          {r.key_metrics.filter((m: any) => m.current && m.current !== 'N/A').map((m: any, i: number) => (
            <MetricRow key={i} metric={m} />
          ))}
        </Card>
      )}

      {r.profitability && (
        <Card title="💰 Profitability">
          <Text style={[styles.bodyText, { color: t.text }]}>{r.profitability.analysis}</Text>
          <View style={styles.statsGrid}>
            <StatBox label="Gross Margin" val={r.profitability.gross_margin_current} prev={r.profitability.gross_margin_previous} />
            <StatBox label="EBITDA Margin" val={r.profitability.ebitda_margin_current} prev={r.profitability.ebitda_margin_previous} />
            <StatBox label="Net Margin" val={r.profitability.net_margin_current} prev={r.profitability.net_margin_previous} />
            <StatBox label="ROE" val={r.profitability.roe} color="#22c55e" />
            <StatBox label="ROA" val={r.profitability.roa} color="#22c55e" />
          </View>
        </Card>
      )}

      {r.growth && (
        <Card title="📈 Growth">
          <Text style={[styles.bodyText, { color: t.text }]}>{r.growth.analysis}</Text>
          <View style={styles.statsGrid}>
            <StatBox label="Revenue Growth YoY" val={r.growth.revenue_growth_yoy} color="#22c55e" />
            <StatBox label="Profit Growth YoY" val={r.growth.profit_growth_yoy} color="#22c55e" />
          </View>
          {r.growth.guidance && r.growth.guidance !== 'N/A' && (
            <View style={[styles.guidanceBox, { backgroundColor: t.accentLight, marginTop: 12 }]}>
              <Text style={[styles.subTitle, { color: t.text }]}>📌 Management Guidance:</Text>
              <Text style={[styles.bodyText, { color: t.text }]}>{r.growth.guidance}</Text>
            </View>
          )}
        </Card>
      )}

      {r.debt && (
        <Card title="🏦 Debt & Leverage">
          <Text style={[styles.bodyText, { color: t.text }]}>{r.debt.analysis}</Text>
          <View style={styles.statsGrid}>
            <StatBox label="Total Debt" val={r.debt.total_debt} />
            <StatBox label="D/E Ratio" val={r.debt.debt_to_equity} />
            <StatBox label="Interest Coverage" val={r.debt.interest_coverage} />
          </View>
        </Card>
      )}

      {r.management_commentary && (
        <Card title="🎙️ Management Commentary">
          {r.management_commentary.overall_tone && (
            <View style={[styles.toneBadge, { backgroundColor: r.management_commentary.overall_tone === 'Positive' ? '#22c55e20' : r.management_commentary.overall_tone === 'Concerned' ? '#ef444420' : '#f59e0b20' }]}>
              <Text style={{ fontWeight: '700', fontSize: 13, color: r.management_commentary.overall_tone === 'Positive' ? '#22c55e' : r.management_commentary.overall_tone === 'Concerned' ? '#ef4444' : '#f59e0b' }}>
                Tone: {r.management_commentary.overall_tone}
              </Text>
            </View>
          )}
          {r.management_commentary.key_points?.length > 0 && (
            <View style={{ marginTop: 10 }}>
              <Text style={[styles.subTitle, { color: t.text }]}>Key Points:</Text>
              {r.management_commentary.key_points.map((p: string, i: number) => (
                <Text key={i} style={[styles.bulletItem, { color: t.text }]}>• {p}</Text>
              ))}
            </View>
          )}
          {r.management_commentary.outlook_statement && r.management_commentary.outlook_statement !== 'N/A' && (
            <View style={[styles.guidanceBox, { backgroundColor: t.accentLight, marginTop: 10 }]}>
              <Text style={[styles.subTitle, { color: t.text }]}>Outlook:</Text>
              <Text style={[styles.bodyText, { color: t.text }]}>{r.management_commentary.outlook_statement}</Text>
            </View>
          )}
        </Card>
      )}

      {r.highlights?.length > 0 && (
        <Card title="✅ Key Strengths">
          {r.highlights.map((h: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <View style={[styles.bulletDotCircle, { backgroundColor: '#22c55e20' }]}><Text style={{ color: '#22c55e', fontSize: 10 }}>✓</Text></View>
              <Text style={[styles.bulletText, { color: t.text }]}>{h}</Text>
            </View>
          ))}
        </Card>
      )}

      {r.risks?.length > 0 && (
        <Card title="⚠️ Key Risks">
          {r.risks.map((risk: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <View style={[styles.bulletDotCircle, { backgroundColor: '#ef444420' }]}><Text style={{ color: '#ef4444', fontSize: 10 }}>!</Text></View>
              <Text style={[styles.bulletText, { color: t.text }]}>{risk}</Text>
            </View>
          ))}
        </Card>
      )}

      {r.what_to_watch?.length > 0 && (
        <Card title="🔭 What to Watch Next">
          {r.what_to_watch.map((w: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <View style={[styles.bulletDotCircle, { backgroundColor: t.accentLight }]}><Text style={{ color: t.accent, fontSize: 10 }}>→</Text></View>
              <Text style={[styles.bulletText, { color: t.text }]}>{w}</Text>
            </View>
          ))}
        </Card>
      )}

      {/* Share section */}
      <View style={[styles.shareSection, { backgroundColor: t.card }]}>
        <Text style={[styles.shareSectionTitle, { color: t.text }]}>Share This Analysis</Text>
        <TouchableOpacity
          style={[styles.copyLinkBtn, { borderColor: linkCopied ? '#22c55e' : t.accent, backgroundColor: linkCopied ? '#22c55e10' : t.accentLight }]}
          onPress={handleCopyLink}
        >
          <Text style={[styles.copyLinkText, { color: linkCopied ? '#22c55e' : t.accent }]}>
            {linkCopied ? '✅ Link Copied!' : '🔗 Copy Shareable Link'}
          </Text>
        </TouchableOpacity>
        <View style={styles.shareRow}>
          <TouchableOpacity style={[styles.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleShareWhatsApp}>
            <Text style={styles.shareBtnText}>💬 WhatsApp</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.shareBtn, { backgroundColor: '#000' }]} onPress={handleShareTwitter}>
            <Text style={styles.shareBtnText}>𝕏 Twitter</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* CTA to sign up */}
      <View style={[styles.ctaCard, { backgroundColor: t.accent }]}>
        <Text style={styles.ctaTitle}>📊 Analyze Your Own Financial Documents</Text>
        <Text style={styles.ctaSubtitle}>Upload any PDF and get AI-powered analysis in seconds</Text>
        <TouchableOpacity style={styles.ctaBtn} onPress={() => router.replace('/')}>
          <Text style={styles.ctaBtnText}>Try FinSight Free →</Text>
        </TouchableOpacity>
      </View>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, marginTop: 8 },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  logoEmoji: { fontSize: 22 },
  logoText: { fontSize: 20, fontWeight: '900' },
  themeToggle: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sharedBanner: { borderRadius: 10, padding: 10, marginBottom: 16, alignItems: 'center' },
  sharedBannerText: { fontSize: 12, fontWeight: '600' },
  header: { marginBottom: 16 },
  company: { fontSize: 24, fontWeight: '800', letterSpacing: -0.5 },
  period: { fontSize: 13, marginTop: 4 },
  currency: { fontSize: 12, marginTop: 2 },
  scoreCard: { borderRadius: 24, padding: 24, alignItems: 'center', marginBottom: 16, shadowColor: '#000', shadowOpacity: 0.08, shadowRadius: 16, elevation: 4 },
  scoreLabel: { fontSize: 11, fontWeight: '600', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 8 },
  scoreCircle: { flexDirection: 'row', alignItems: 'flex-end' },
  score: { fontSize: 72, fontWeight: '900', lineHeight: 80 },
  scoreMax: { fontSize: 24, fontWeight: '600', marginBottom: 12 },
  scoreBadge: { borderRadius: 20, paddingHorizontal: 18, paddingVertical: 5, marginTop: 8 },
  scoreTag: { fontSize: 15, fontWeight: '700' },
  scoreComponentBox: { borderRadius: 12, padding: 12, marginBottom: 8 },
  ratingBadge: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  progressBarBg: { height: 6, borderRadius: 3, overflow: 'hidden' },
  progressBarFill: { height: 6, borderRadius: 3 },
  card: { borderRadius: 18, padding: 18, marginBottom: 14, shadowColor: '#000', shadowOpacity: 0.04, shadowRadius: 8, elevation: 2 },
  cardTitle: { fontSize: 15, fontWeight: '700', marginBottom: 12 },
  bodyText: { fontSize: 14, lineHeight: 22 },
  verdictBox: { borderRadius: 12, padding: 14 },
  metricsHeader: { flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 8, borderBottomWidth: 1, marginBottom: 4 },
  metricsHeaderText: { fontSize: 10, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 10, borderBottomWidth: 1 },
  metricLeft: { flex: 1, paddingRight: 8 },
  metricLabel: { fontSize: 13, fontWeight: '500' },
  metricComment: { fontSize: 11, marginTop: 2, fontStyle: 'italic' },
  metricRight: { alignItems: 'flex-end', minWidth: 100 },
  metricCurrent: { fontSize: 14, fontWeight: '700' },
  metricPrevious: { fontSize: 11, marginTop: 1 },
  metricChange: { fontSize: 12, marginTop: 2, fontWeight: '600' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12, gap: 8 },
  statBox: { borderRadius: 12, padding: 12, minWidth: '30%', flex: 1, alignItems: 'center' },
  statValue: { fontSize: 16, fontWeight: '700' },
  statPrev: { fontSize: 10, marginTop: 1 },
  statLabel: { fontSize: 10, marginTop: 4, textAlign: 'center' },
  subTitle: { fontSize: 13, fontWeight: '700', marginBottom: 6 },
  guidanceBox: { borderRadius: 10, padding: 12 },
  toneBadge: { borderRadius: 8, padding: 10, marginBottom: 8, alignSelf: 'flex-start' },
  bulletRow: { flexDirection: 'row', marginBottom: 10, alignItems: 'flex-start' },
  bulletDotCircle: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center', marginRight: 10, marginTop: 2, flexShrink: 0 },
  bulletText: { fontSize: 14, lineHeight: 22, flex: 1 },
  bulletItem: { fontSize: 13, lineHeight: 22, marginBottom: 4 },
  shareSection: { borderRadius: 18, padding: 18, marginBottom: 14 },
  shareSectionTitle: { fontSize: 15, fontWeight: '700', marginBottom: 12 },
  copyLinkBtn: { borderRadius: 12, padding: 14, alignItems: 'center', borderWidth: 1.5, marginBottom: 10 },
  copyLinkText: { fontSize: 14, fontWeight: '700' },
  shareRow: { flexDirection: 'row', gap: 10 },
  shareBtn: { flex: 1, borderRadius: 12, padding: 14, alignItems: 'center' },
  shareBtnText: { color: '#fff', fontSize: 13, fontWeight: '700' },
  ctaCard: { borderRadius: 18, padding: 24, marginBottom: 14, alignItems: 'center' },
  ctaTitle: { fontSize: 16, fontWeight: '800', color: '#fff', textAlign: 'center', marginBottom: 6 },
  ctaSubtitle: { fontSize: 13, color: 'rgba(255,255,255,0.8)', textAlign: 'center', marginBottom: 16 },
  ctaBtn: { backgroundColor: '#fff', borderRadius: 12, paddingHorizontal: 24, paddingVertical: 12 },
  ctaBtnText: { color: '#0052FF', fontSize: 15, fontWeight: '800' },
  btn: { borderRadius: 14, padding: 16, alignItems: 'center', paddingHorizontal: 32 },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
