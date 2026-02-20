import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../../src/api';

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
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
        <Text style={styles.backText}>← Back</Text>
      </TouchableOpacity>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.company}>{r.company_name || 'Financial Analysis'}</Text>
        <Text style={styles.period}>{r.statement_type?.replace(/_/g, ' ')} · {r.period} · {r.currency}</Text>
      </View>

      {/* Health Score */}
      <View style={styles.scoreCard}>
        <Text style={styles.scoreLabel}>Financial Health Score</Text>
        <Text style={[styles.score, { color: scoreColor }]}>{r.health_score}/100</Text>
        <View style={[styles.scoreBadge, { backgroundColor: scoreColor + '20' }]}>
          <Text style={[styles.scoreTag, { color: scoreColor }]}>{r.health_label}</Text>
        </View>
      </View>

      {/* Summary */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>📋 Executive Summary</Text>
        <Text style={styles.bodyText}>{r.summary}</Text>
      </View>

      {/* Investor Verdict */}
      {r.investor_verdict && (
        <View style={[styles.card, { backgroundColor: '#EEF4FF' }]}>
          <Text style={styles.cardTitle}>💡 Plain English Verdict</Text>
          <Text style={styles.bodyText}>{r.investor_verdict}</Text>
        </View>
      )}

      {/* Key Metrics */}
      {r.key_metrics && r.key_metrics.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>📊 Key Metrics</Text>
          {r.key_metrics.filter((m: any) => m.value && m.value !== 'N/A').map((m: any, i: number) => (
            <View key={i} style={styles.metricRow}>
              <Text style={styles.metricLabel}>{m.label}</Text>
              <View style={styles.metricRight}>
                <Text style={styles.metricValue}>{m.value}</Text>
                {m.change && m.change !== 'N/A' && (
                  <Text style={[styles.metricChange, { color: m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : '#888' }]}>
                    {m.trend === 'up' ? '↑' : m.trend === 'down' ? '↓' : '→'} {m.change}
                  </Text>
                )}
              </View>
            </View>
          ))}
        </View>
      )}

      {/* Profitability */}
      {r.profitability && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>💰 Profitability Analysis</Text>
          <Text style={styles.bodyText}>{r.profitability.analysis}</Text>
          <View style={styles.statsGrid}>
            {r.profitability.gross_margin && r.profitability.gross_margin !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.profitability.gross_margin}</Text>
                <Text style={styles.statLabel}>Gross Margin</Text>
              </View>
            )}
            {r.profitability.net_margin && r.profitability.net_margin !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.profitability.net_margin}</Text>
                <Text style={styles.statLabel}>Net Margin</Text>
              </View>
            )}
            {r.profitability.roe && r.profitability.roe !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.profitability.roe}</Text>
                <Text style={styles.statLabel}>ROE</Text>
              </View>
            )}
            {r.profitability.roa && r.profitability.roa !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.profitability.roa}</Text>
                <Text style={styles.statLabel}>ROA</Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Growth */}
      {r.growth && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>📈 Growth Analysis</Text>
          <Text style={styles.bodyText}>{r.growth.analysis}</Text>
          <View style={styles.statsGrid}>
            {r.growth.revenue_growth && r.growth.revenue_growth !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={[styles.statValue, { color: '#22c55e' }]}>{r.growth.revenue_growth}</Text>
                <Text style={styles.statLabel}>Revenue Growth</Text>
              </View>
            )}
            {r.growth.profit_growth && r.growth.profit_growth !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={[styles.statValue, { color: '#22c55e' }]}>{r.growth.profit_growth}</Text>
                <Text style={styles.statLabel}>Profit Growth</Text>
              </View>
            )}
          </View>
          {r.growth.yoy_comparison && <Text style={[styles.bodyText, { marginTop: 8, fontStyle: 'italic' }]}>{r.growth.yoy_comparison}</Text>}
        </View>
      )}

      {/* Liquidity */}
      {r.liquidity && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>💧 Liquidity Position</Text>
          <Text style={styles.bodyText}>{r.liquidity.analysis}</Text>
          <View style={styles.statsGrid}>
            {r.liquidity.current_ratio && r.liquidity.current_ratio !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.liquidity.current_ratio}</Text>
                <Text style={styles.statLabel}>Current Ratio</Text>
              </View>
            )}
            {r.liquidity.quick_ratio && r.liquidity.quick_ratio !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.liquidity.quick_ratio}</Text>
                <Text style={styles.statLabel}>Quick Ratio</Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Debt */}
      {r.debt && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>🏦 Debt & Leverage</Text>
          <Text style={styles.bodyText}>{r.debt.analysis}</Text>
          <View style={styles.statsGrid}>
            {r.debt.debt_to_equity && r.debt.debt_to_equity !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.debt.debt_to_equity}</Text>
                <Text style={styles.statLabel}>Debt/Equity</Text>
              </View>
            )}
            {r.debt.interest_coverage && r.debt.interest_coverage !== 'N/A' && (
              <View style={styles.statBox}>
                <Text style={styles.statValue}>{r.debt.interest_coverage}</Text>
                <Text style={styles.statLabel}>Interest Coverage</Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Highlights */}
      {r.highlights && r.highlights.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>✅ Key Strengths</Text>
          {r.highlights.map((h: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={styles.bulletDot}>●</Text>
              <Text style={styles.bulletText}>{h}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Risks */}
      {r.risks && r.risks.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>⚠️ Key Risks</Text>
          {r.risks.map((risk: string, i: number) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={[styles.bulletDot, { color: '#ef4444' }]}>●</Text>
              <Text style={styles.bulletText}>{risk}</Text>
            </View>
          ))}
        </View>
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
  company: { fontSize: 26, fontWeight: 'bold', color: '#1a1a2e' },
  period: { fontSize: 13, color: '#666', marginTop: 4, textTransform: 'capitalize' },
  scoreCard: { backgroundColor: '#fff', borderRadius: 20, padding: 28, alignItems: 'center', marginBottom: 16, shadowColor: '#0052FF', shadowOpacity: 0.1, shadowRadius: 12, elevation: 4 },
  scoreLabel: { fontSize: 13, color: '#888', marginBottom: 8, fontWeight: '500' },
  score: { fontSize: 64, fontWeight: 'bold', lineHeight: 72 },
  scoreBadge: { borderRadius: 20, paddingHorizontal: 16, paddingVertical: 4, marginTop: 8 },
  scoreTag: { fontSize: 16, fontWeight: '700' },
  card: { backgroundColor: '#fff', borderRadius: 16, padding: 18, marginBottom: 14, shadowColor: '#000', shadowOpacity: 0.04, shadowRadius: 8, elevation: 2 },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#1a1a2e', marginBottom: 12 },
  bodyText: { fontSize: 14, color: '#444', lineHeight: 22 },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f5f5f5' },
  metricLabel: { fontSize: 13, color: '#555', flex: 1 },
  metricRight: { alignItems: 'flex-end' },
  metricValue: { fontSize: 14, fontWeight: '700', color: '#1a1a2e' },
  metricChange: { fontSize: 12, marginTop: 2, fontWeight: '500' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 12, gap: 8 },
  statBox: { backgroundColor: '#f8faff', borderRadius: 12, padding: 12, minWidth: '45%', flex: 1, alignItems: 'center' },
  statValue: { fontSize: 18, fontWeight: '700', color: '#0052FF' },
  statLabel: { fontSize: 11, color: '#888', marginTop: 4, textAlign: 'center' },
  bulletRow: { flexDirection: 'row', marginBottom: 8, alignItems: 'flex-start' },
  bulletDot: { color: '#22c55e', fontSize: 10, marginRight: 8, marginTop: 5 },
  bulletText: { fontSize: 14, color: '#444', lineHeight: 22, flex: 1 },
  btn: { backgroundColor: '#0052FF', borderRadius: 14, padding: 16, alignItems: 'center', marginTop: 8 },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
