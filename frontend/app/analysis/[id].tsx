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

  useEffect(() => {
    fetchAnalysis();
  }, [id]);

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

  if (error) return (
    <View style={styles.center}>
      <Text style={styles.errorText}>{error}</Text>
    </View>
  );

  if (!analysis || !analysis.result) return (
    <View style={styles.center}>
      <Text style={styles.errorText}>No results found</Text>
      <TouchableOpacity style={styles.button} onPress={() => router.back()}>
        <Text style={styles.buttonText}>Go Back</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';

  return (
    <ScrollView style={styles.container}>
      <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
        <Text style={styles.backText}>← Back</Text>
      </TouchableOpacity>

      <View style={styles.header}>
        <Text style={styles.company}>{r.company_name || 'Financial Analysis'}</Text>
        <Text style={styles.period}>{r.statement_type} · {r.period} · {r.currency}</Text>
      </View>

      <View style={styles.scoreCard}>
        <Text style={styles.scoreLabel}>Financial Health Score</Text>
        <Text style={[styles.score, { color: scoreColor }]}>{r.health_score}/100</Text>
        <Text style={[styles.scoreTag, { color: scoreColor }]}>{r.health_label}</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>📋 Summary</Text>
        <Text style={styles.summary}>{r.summary}</Text>
      </View>

      {r.key_metrics && r.key_metrics.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>📊 Key Metrics</Text>
          {r.key_metrics.map((m: any, i: number) => (
            <View key={i} style={styles.metricRow}>
              <Text style={styles.metricLabel}>{m.label}</Text>
              <View style={styles.metricRight}>
                <Text style={styles.metricValue}>{m.value}</Text>
                <Text style={[styles.metricChange, { color: m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : '#888' }]}>
                  {m.change}
                </Text>
              </View>
            </View>
          ))}
        </View>
      )}

      {r.highlights && r.highlights.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>✅ Highlights</Text>
          {r.highlights.map((h: string, i: number) => (
            <Text key={i} style={styles.highlight}>• {h}</Text>
          ))}
        </View>
      )}

      {r.risks && r.risks.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>⚠️ Risks</Text>
          {r.risks.map((risk: string, i: number) => (
            <Text key={i} style={styles.risk}>• {risk}</Text>
          ))}
        </View>
      )}

      <TouchableOpacity style={styles.button} onPress={() => router.back()}>
        <Text style={styles.buttonText}>Back to Home</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f8fafc', padding: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  loadingText: { marginTop: 12, color: '#666', fontSize: 16 },
  errorText: { color: '#ef4444', fontSize: 16, textAlign: 'center' },
  backBtn: { marginBottom: 16, marginTop: 8 },
  backText: { color: '#0052FF', fontSize: 16 },
  header: { marginBottom: 20 },
  company: { fontSize: 24, fontWeight: 'bold', color: '#1a1a2e' },
  period: { fontSize: 14, color: '#666', marginTop: 4, textTransform: 'capitalize' },
  scoreCard: { backgroundColor: '#fff', borderRadius: 16, padding: 24, alignItems: 'center', marginBottom: 16, shadowColor: '#000', shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  scoreLabel: { fontSize: 14, color: '#666', marginBottom: 8 },
  score: { fontSize: 56, fontWeight: 'bold' },
  scoreTag: { fontSize: 18, fontWeight: '600', marginTop: 4 },
  section: { backgroundColor: '#fff', borderRadius: 16, padding: 16, marginBottom: 16, shadowColor: '#000', shadowOpacity: 0.05, shadowRadius: 8, elevation: 2 },
  sectionTitle: { fontSize: 16, fontWeight: 'bold', color: '#1a1a2e', marginBottom: 12 },
  summary: { fontSize: 14, color: '#444', lineHeight: 22 },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  metricLabel: { fontSize: 14, color: '#444', flex: 1 },
  metricRight: { alignItems: 'flex-end' },
  metricValue: { fontSize: 14, fontWeight: '600', color: '#1a1a2e' },
  metricChange: { fontSize: 12, marginTop: 2 },
  highlight: { fontSize: 14, color: '#444', lineHeight: 24, marginBottom: 4 },
  risk: { fontSize: 14, color: '#444', lineHeight: 24, marginBottom: 4 },
  button: { backgroundColor: '#0052FF', borderRadius: 12, padding: 16, alignItems: 'center', marginVertical: 20 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});