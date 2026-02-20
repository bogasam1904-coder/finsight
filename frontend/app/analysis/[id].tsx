import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../../src/api';

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <View style={styles.card}>
    <Text style={styles.cardTitle}>{title}</Text>
    {children}
  </View>
);

const MetricRow = ({ metric }: { metric: any }) => {
  const trendColor = metric.trend === 'up' ? '#22c55e' : metric.trend === 'down' ? '#ef4444' : '#888';
  const trendIcon = metric.trend === 'up' ? '↑' : metric.trend === 'down' ? '↓' : '→';
  return (
    <View style={styles.metricRow}>
      <View style={styles.metricLeft}>
        <Text style={styles.metricLabel}>{metric.label}</Text>
        {metric.comment && metric.comment !== 'N/A' && (
          <Text style={styles.metricComment}>{metric.comment}</Text>
        )}
      </View>
      <View style={styles.metricRight}>
        <Text style={styles.metricCurrent}>{metric.current}</Text>
        {metric.previous && metric.previous !== 'N/A' && (
          <Text style={styles.metricPrevious}>vs {metric.previous}</Text>
        )}
        {metric.change && metric.change !== 'N/A' && (
          <Text style={[styles.metricChange, { color: trendColor }]}>
            {trendIcon} {metric.change}
          </Text>
        )}
      </View>
    </View>
  );
};

export default function AnalysisScreen() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => { fetchAnalysis(); }, [id]);

  const fetchAnalysis = async () => {
    try {
      const res = await apiFetch(`/analyses/${id}`);
      const data = await res.json();
      setAnalysis(data);
    } catch (e) {
      setError('Failed to load analysis');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color="#0052FF" />
      <Text style={styles.loadingText}>Loading analysis...</Text>
    </View>
  );

  if (error || !analysis || !analysis.result) return (
    <View style={styles.center}>
      <Text style={styles.errorText}>{error || 'No results found'}</Text>
      <TouchableOpacity style={styles.btn} onPress={() => router.back()}>
        <Text style={styles.btnText}>Go Back</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : r.health_score >= 40 ? '#ef4444' : '#7f1d1d';

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
        <Text style={styles.backText}>← Back</Text>
      </TouchableOpacity>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.company}>{r.company_name || 'Financial Analysis'}</Text>
        <Text style={styles.period}>{r.statement_type} · {r.period}</Text>
        <Text style={styles.currency}>{r.currency}</Text>
      </View>

      {/* Health Score */}
      <View style={styles.scoreCard}>
        <Text style={styles.scoreLabel}>Financial Health Score</Text>
        <Text style={[styles.score, { color: scoreColor }]}>{r.health_score}/100</Text>
        <View style={[styles.scoreBadge, { backgroundColor: scoreColor + '20' }]}>
          <Text style={[styles.scoreTag, { color: scoreColor }]}>{r.health_label}</Text>
        </View>
        {r.health_score_derivation && (
          <View style={styles.scoreDerivation}>
            <Text style={styles.scoreDerivationTitle}>How this score was calculated:</Text>
            <Text style={styles.scoreDerivationText}>{r.health_score_derivation}</Text>
          </View>
        )}
      </View>

      {/* Executive Summary */}
      <Section title="📋 Executive Summary">
        <Text style={styles.bodyText}>{r.executive_summary}</Text>
      </Section>

      {/* Plain English Verdict */}
      {r.investor_verdict && (
        <View style={[styles.card, { backgroundColor: '#EEF4FF', borderLeftWidth: 4, borderLeftColor: '#0052FF' }]}>
          <Text style={styles.cardTitle}>💡 What This Means (Plain English)</Text>
          <Text style={styles.bodyText}>{r.investor_verdict}</Text>
        </View>
      )}

      {/* Key Metrics */}
      {r.key_metrics && r.key_metrics.length > 0 && (
        <Section title="📊 Key Financial Metrics">
          <View style={styles.metricsHeader}>
            <Text style={styles.metricsHeaderLeft}>Metric</Text>
            <Text style={styles.metricsHeaderRight}>Current | Previous | Change</Text>
          </View>
          {r.key_metrics.filter((m: any) => m.current && m.current !== 'N/A').map((m: any, i: number) => (
            <MetricRow key={i} metric={m} />
          ))}
        </Section>
      )}

      {/* Profitability */}
      {r.profitability && (
        <Section title="💰 Profitability Analysis">
          <Text style={styles.bodyText}>{r.profitability.analysis}</Text>
          <View style={styles.statsGrid}>
            {[
              { label: 'Gross Margin', cur: r.profitability.gross_margin_current, prev: r.profitability.gross_margin_previous },
              { label: 'EBITDA Margin', cur: r.profitability.ebitda_margin_current, prev: r.profitability.ebitda_margin_previous },
              { label: 'Net Margin', cur: r.profitability.net_margin_current, prev: r.profitability.net_margin_previous },
              { label: 'ROE', cur: r.profitability.roe, prev: null },
              { label: 'ROA', cur: r.profitability.roa, prev: null },
            ].filter(s => s.cur && s.cur !== 'N/A').map((s, i) => (
              <View key={i} style={styles.statBox}>
                <Text style={styles.statValue}>{s.cur}</Text>
                {s.prev && s.prev !== 'N/A' && <Text style={styles.statPrev}>vs {s.prev}</Text>}
                <Text style={styles.statLabel}>{s.label}</Text>
              </View>
            ))}
          </View>
          {r.profitability.key_cost_drivers && r.profitability.key_cost_drivers.length > 0 && (
            <View style={{ marginTop: 12 }}>
              <Text style={styles.subTitle}>Key Cost Drivers:</Text>
              {r.profitability.key_cost_drivers.map((c: string, i: number) => (
                <Text key={i} style={styles.bulletItem}>• {c}</Text>
              ))}
            </View>
          )}
        </Section>
      )}

      {/* Growth */}
      {r.growth && (
        <Section title="📈 Growth Analysis">
          <Text style={styles.bodyText}>{r.growth.analysis}</Text>
          <View style={styles.statsGrid}>
            {r.growth.revenue_growth_yoy && r.growth.revenue_growth_yoy !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={[styles.statValue, { color: '#22c55e' }]}>{r.growth.revenue_growth_yoy}</Text>
                <Text style={styles.statLabel}>Revenue Growth YoY</Text>
              </View>
            )}
            {r.growth.profit_growth_yoy && r.growth.profit_growth_yoy !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={[styles.statValue, { color: '#22c55e' }]}>{r.growth.profit_growth_yoy}</Text>
                <Text style={styles.statLabel}>Profit Growth YoY</Text>
              </View>
            )}
          </View>
          {r.growth.guidance && r.growth.guidance !== 'N/A' && (
            <View style={styles.guidanceBox}>
              <Text style={styles.subTitle}>Management Guidance:</Text>
              <Text style={styles.bodyText}>{r.growth.guidance}</Text>
            </View>
          )}
        </Section>
      )}

      {/* Liquidity */}
      {r.liquidity && (
        <Section title="💧 Liquidity & Cash Position">
          <Text style={styles.bodyText}>{r.liquidity.analysis}</Text>
          <View style={styles.statsGrid}>
            {[
              { label: 'Current Ratio', val: r.liquidity.current_ratio },
              { label: 'Quick Ratio', val: r.liquidity.quick_ratio },
              { label: 'Cash Position', val: r.liquidity.cash_position },
              { label: 'Operating Cash Flow', val: r.liquidity.operating_cash_flow },
              { label: 'Free Cash Flow', val: r.liquidity.free_cash_flow },
            ].filter(s => s.val && s.val !== 'N/A').map((s, i) => (
              <View key={i} style={styles.statBox}>
                <Text style={styles.statValue}>{s.val}</Text>
                <Text style={styles.statLabel}>{s.label}</Text>
              </View>
            ))}
          </View>
        </Section>
      )}

      {/* Debt */}
      {r.debt && (
        <Section title="🏦 Debt & Leverage">
          <Text style={styles.bodyText}>{r.debt.analysis}</Text>
          <View style={styles.statsGrid}>
            {[
              { label: 'Total Debt', val: r.debt.total_debt },
              { label: 'Net Debt', val: r.debt.net_debt },
              { label: 'Debt/Equity', val: r.debt.debt_to_equity },
              { label: 'Interest Coverage', val: r.debt.interest_coverage },
            ].filter(s => s.val && s.val !== 'N/A').map((s, i) => (
              <View key={i} style={styles.statBox}>
                <Text style={styles.statValue}>{s.val}</Text>
                <Text style={styles.statLabel}>{s.label}</Text>
              </View>
            ))}
          </View>
          {r.debt.debt_trend && (
            <Text style={styles.debtTrend}>Debt Trend: <Text style={{ fontWeight: '700', color: r.debt.debt_trend === 'Decreasing' ? '#22c55e' : r.debt.debt_trend === 'Increasing' ? '#ef4444' : '#888' }}>{r.debt.debt_trend}</Text></Text>
          )}
        </Section>
      )}

      {/* Management Commentary */}
      {r.management_commentary && (
        <Section title="🎙️ Management Commentary">
          {r.management_commentary.overall_tone && (
            <View style={styles.toneBox}>
              <Text style={styles.toneLabel}>Overall Tone: </Text>
              <Text style={[styles.toneValue, {
                color: r.management_commentary.overall_tone === 'Positive' ? '#22c55e' :
                  r.management_commentary.overall_tone === 'Concerned' ? '#ef4444' : '#f59e0b'
              }]}>{r.management_commentary.overall_tone}</Text>
            </View>
          )}
          {r.management_commentary.key_points && r.management_commentary.key_points.length > 0 && (
            <View style={{ marginBottom: 12 }}>
              <Text style={styles.subTitle}>Key Points:</Text>
              {r.management_commentary.key_points.map((p: string, i: number) => (
                <Text key={i} style={styles.bulletItem}>• {p}</Text>
              ))}
            </View>
          )}
          {r.management_commentary.outlook_statement && r.management_commentary.outlook_statement !== 'N/A' && (
            <View style={styles.guidanceBox}>
              <Text style={styles.subTitle}>Outlook:</Text>
              <Text style={styles.bodyText}>{r.management_commentary.outlook_statement}</Text>
            </View>
          )}
          {r.management_commentary.concerns_raised && r.management_commentary.concerns_raised.length > 0 && (
            <View style={{ marginTop: 8 }}>
              <Text style={styles.subTitle}>Concerns Acknowledged:</Text>
              {r.management_commentary.concerns_raised.map((c: string, i: number) => (
                <Text key={i} style={[styles.bulletItem, { color: '#ef4444' }]}>• {c}</Text>
              ))}
            </View>
          )}
        </Section>
      )}

      {/* Segments */}
      {r.segments && r.segments.length > 0 && (
        <Section title="🏢 Business Segments">
          {r.segments.map((seg: any, i: number) => (
            <View key={i} style={styles.segmentBox}>
              <Text style={styles.segmentName}>{seg.name}</Text>
              <View style={styles.segmentStats}>
                {seg.revenue && <Text style={styles.segmentStat}>Revenue: {seg.revenue}</Text>}
                {seg.growth && <Text style={styles.segmentStat}>Growth: {seg.growth}</Text>}
                {seg.margin && <Text style={styles.segmentStat}>Margin: {seg.margin}</Text>}
              </View>
              {seg.comment && <Text style={styles.metricComment}>{seg.comment}</Text>}
            </View>
          ))}
        </Section>
      )}

      {/* Highlights */}
      {r.highlights && r.highlights.length > 0 && (
        <Section title="✅ Key Strengths">
          {r.highlights.map((h: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={[styles.bulletDot, { color: '#22c55e' }]}>●</Text>
              <Text style={styles.bulletText}>{h}</Text>
            </View>
          ))}
        </Section>
      )}

      {/* Risks */}
      {r.risks && r.risks.length > 0 && (
        <Section title="⚠️ Key Risks">
          {r.risks.map((risk: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={[styles.bulletDot, { color: '#ef4444' }]}>●</Text>
              <Text style={styles.bulletText}>{risk}</Text>
            </View>
          ))}
        </Section>
      )}

      {/* What to Watch */}
      {r.what_to_watch && r.what_to_watch.length > 0 && (
        <Section title="🔭 What to Watch Next">
          {r.what_to_watch.map((w: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={[styles.bulletDot, { color: '#0052FF' }]}>●</Text>
              <Text style={styles.bulletText}>{w}</Text>
            </View>
          ))}
        </Section>
      )}

      <TouchableOpacity style={styles.btn} onPress={() => router.back()}>
        <Text style={styles.btnText}>Back to Home</Text>
      </TouchableOpacity>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f0f4ff', padding: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20, backgroundColor: '#f0f4ff' },
  loadingText: { marginTop: 12, color: '#666', fontSize: 16 },
  errorText: { color: '#ef4444', fontSize: 16, textAlign: 'center', marginBottom: 16 },
  backBtn: { marginBottom: 12, marginTop: 8 },
  backText: { color: '#0052FF', fontSize: 16, fontWeight: '500' },
  header: { marginBottom: 16 },
  company: { fontSize: 24, fontWeight: 'bold', color: '#1a1a2e' },
  period: { fontSize: 13, color: '#555', marginTop: 4 },
  currency: { fontSize: 12, color: '#888', marginTop: 2 },
  scoreCard: { backgroundColor: '#fff', borderRadius: 20, padding: 24, alignItems: 'center', marginBottom: 16, shadowColor: '#0052FF', shadowOpacity: 0.1, shadowRadius: 12, elevation: 4 },
  scoreLabel: { fontSize: 13, color: '#888', marginBottom: 8, fontWeight: '500' },
  score: { fontSize: 64, fontWeight: 'bold', lineHeight: 72 },
  scoreBadge: { borderRadius: 20, paddingHorizontal: 16, paddingVertical: 4, marginTop: 8 },
  scoreTag: { fontSize: 16, fontWeight: '700' },
  scoreDerivation: { marginTop: 16, backgroundColor: '#f8faff', borderRadius: 12, padding: 12, width: '100%' },
  scoreDerivationTitle: { fontSize: 12, fontWeight: '700', color: '#555', marginBottom: 4 },
  scoreDerivationText: { fontSize: 12, color: '#666', lineHeight: 18 },
  card: { backgroundColor: '#fff', borderRadius: 16, padding: 18, marginBottom: 14, shadowColor: '#000', shadowOpacity: 0.04, shadowRadius: 8, elevation: 2 },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#1a1a2e', marginBottom: 12 },
  bodyText: { fontSize: 14, color: '#444', lineHeight: 22 },
  metricsHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: '#eee' },
  metricsHeaderLeft: { fontSize: 11, color: '#888', fontWeight: '600' },
  metricsHeaderRight: { fontSize: 11, color: '#888', fontWeight: '600' },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f5f5f5' },
  metricLeft: { flex: 1, paddingRight: 8 },
  metricLabel: { fontSize: 13, color: '#333', fontWeight: '500' },
  metricComment: { fontSize: 11, color: '#888', marginTop: 2, fontStyle: 'italic' },
  metricRight: { alignItems: 'flex-end', minWidth: 100 },
  metricCurrent: { fontSize: 14, fontWeight: '700', color: '#1a1a2e' },
  metricPrevious: { fontSize: 11, color: '#888', marginTop: 1 },
  metricChange: { fontSize: 12, marginTop: 2, fontWeight: '600' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12, gap: 8 },
  statBox: { backgroundColor: '#f8faff', borderRadius: 12, padding: 12, minWidth: '30%', flex: 1, alignItems: 'center' },
  statValue: { fontSize: 16, fontWeight: '700', color: '#0052FF' },
  statPrev: { fontSize: 10, color: '#888', marginTop: 1 },
  statLabel: { fontSize: 10, color: '#888', marginTop: 4, textAlign: 'center' },
  subTitle: { fontSize: 13, fontWeight: '700', color: '#333', marginBottom: 6 },
  guidanceBox: { backgroundColor: '#f0f9ff', borderRadius: 10, padding: 12, marginTop: 10 },
  debtTrend: { fontSize: 13, color: '#555', marginTop: 10 },
  toneBox: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  toneLabel: { fontSize: 13, color: '#555', fontWeight: '600' },
  toneValue: { fontSize: 14, fontWeight: '700' },
  bulletRow: { flexDirection: 'row', marginBottom: 8, alignItems: 'flex-start' },
  bulletDot: { fontSize: 10, marginRight: 8, marginTop: 5 },
  bulletText: { fontSize: 14, color: '#444', lineHeight: 22, flex: 1 },
  bulletItem: { fontSize: 13, color: '#444', lineHeight: 22, marginBottom: 4 },
  segmentBox: { backgroundColor: '#f8faff', borderRadius: 10, padding: 12, marginBottom: 8 },
  segmentName: { fontSize: 14, fontWeight: '700', color: '#1a1a2e', marginBottom: 4 },
  segmentStats: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 4 },
  segmentStat: { fontSize: 12, color: '#0052FF', backgroundColor: '#EEF4FF', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  btn: { backgroundColor: '#0052FF', borderRadius: 14, padding: 16, alignItems: 'center', marginTop: 8 },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
