import React, { useEffect, useState, useContext, createContext } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Dimensions, Switch
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../../src/api';

const ThemeContext = createContext({ dark: false, toggle: () => {} });

const { width } = Dimensions.get('window');

// Simple Bar Chart Component
const BarChart = ({ data, valueKey, labelKey, color, title, prefix = '' }: any) => {
  if (!data || data.length === 0 || data.every((d: any) => !d[valueKey] || d[valueKey] === 0)) return null;
  const max = Math.max(...data.map((d: any) => Number(d[valueKey]) || 0));
  if (max === 0) return null;
  const { dark } = useContext(ThemeContext);
  const t = dark ? darkTheme : lightTheme;
  return (
    <View style={{ marginTop: 16 }}>
      <Text style={[styles.subTitle, { color: t.text }]}>{title}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'flex-end', height: 100, marginTop: 8, gap: 6 }}>
        {data.map((d: any, i: number) => {
          const val = Number(d[valueKey]) || 0;
          const h = max > 0 ? (val / max) * 80 : 0;
          return (
            <View key={i} style={{ flex: 1, alignItems: 'center', justifyContent: 'flex-end' }}>
              <Text style={{ fontSize: 9, color: t.textSecondary, marginBottom: 2 }}>{prefix}{val > 0 ? val.toLocaleString() : '-'}</Text>
              <View style={{ width: '80%', height: h, backgroundColor: color, borderRadius: 4, opacity: 0.85 }} />
              <Text style={{ fontSize: 9, color: t.textSecondary, marginTop: 3 }}>{d[labelKey]}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
};

// Score Breakdown Component
const ScoreBreakdown = ({ breakdown }: { breakdown: any }) => {
  const { dark } = useContext(ThemeContext);
  const t = dark ? darkTheme : lightTheme;
  if (!breakdown || !breakdown.components) return null;
  const colors: Record<string, string> = {
    'Strong': '#22c55e',
    'Moderate': '#f59e0b',
    'Weak': '#ef4444'
  };
  return (
    <View style={{ marginTop: 12 }}>
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
              <View style={[styles.progressBarFill, { width: `${pct}%`, backgroundColor: barColor }]} />
            </View>
            <Text style={{ fontSize: 12, color: t.textSecondary, marginTop: 6, lineHeight: 18 }}>{c.reasoning}</Text>
          </View>
        );
      })}
    </View>
  );
};

const lightTheme = {
  bg: '#F0F4FF',
  card: '#FFFFFF',
  cardAlt: '#F8FAFF',
  text: '#0A0E1A',
  textSecondary: '#6B7280',
  border: '#E5E7EB',
  accent: '#0052FF',
  accentLight: '#EEF4FF',
};

const darkTheme = {
  bg: '#0A0E1A',
  card: '#141826',
  cardAlt: '#1C2233',
  text: '#F1F5F9',
  textSecondary: '#94A3B8',
  border: '#2D3748',
  accent: '#4F8AFF',
  accentLight: '#1A2540',
};

export default function AnalysisScreen() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dark, setDark] = useState(false);

  const t = dark ? darkTheme : lightTheme;

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
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={[styles.loadingText, { color: t.textSecondary }]}>Preparing your analysis...</Text>
    </View>
  );

  if (error || !analysis || !analysis.result) return (
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <Text style={[styles.errorText]}>{'No results found'}</Text>
      <TouchableOpacity style={[styles.btn, { backgroundColor: t.accent }]} onPress={() => router.back()}>
        <Text style={styles.btnText}>Go Back</Text>
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
    <ThemeContext.Provider value={{ dark, toggle: () => setDark(d => !d) }}>
      <ScrollView style={[styles.container, { backgroundColor: t.bg }]} showsVerticalScrollIndicator={false}>

        {/* Top Bar */}
        <View style={styles.topBar}>
          <TouchableOpacity onPress={() => router.back()}>
            <Text style={[styles.backText, { color: t.accent }]}>← Back</Text>
          </TouchableOpacity>
          <View style={styles.themeToggle}>
            <Text style={[styles.themeLabel, { color: t.textSecondary }]}>{dark ? '🌙' : '☀️'}</Text>
            <Switch
              value={dark}
              onValueChange={setDark}
              trackColor={{ false: '#CBD5E1', true: '#4F8AFF' }}
              thumbColor={dark ? '#fff' : '#fff'}
            />
          </View>
        </View>

        {/* Header */}
        <View style={styles.header}>
          <Text style={[styles.company, { color: t.text }]}>{r.company_name || 'Financial Analysis'}</Text>
          <Text style={[styles.period, { color: t.textSecondary }]}>{r.statement_type} · {r.period}</Text>
          <Text style={[styles.currency, { color: t.textSecondary }]}>{r.currency}</Text>
        </View>

        {/* Health Score Card */}
        <View style={[styles.scoreCard, { backgroundColor: t.card }]}>
          <Text style={[styles.scoreLabel, { color: t.textSecondary }]}>Financial Health Score</Text>
          <View style={styles.scoreCircle}>
            <Text style={[styles.score, { color: scoreColor }]}>{r.health_score}</Text>
            <Text style={[styles.scoreMax, { color: t.textSecondary }]}>/100</Text>
          </View>
          <View style={[styles.scoreBadge, { backgroundColor: scoreColor + '20' }]}>
            <Text style={[styles.scoreTag, { color: scoreColor }]}>{r.health_label}</Text>
          </View>
          {r.health_score_breakdown && (
            <ScoreBreakdown breakdown={r.health_score_breakdown} />
          )}
        </View>

        {/* Executive Summary */}
        <Card title="📋 Executive Summary">
          <Text style={[styles.bodyText, { color: t.text }]}>{r.executive_summary}</Text>
        </Card>

        {/* Plain English */}
        {r.investor_verdict && (
          <Card title="💡 What This Means (Plain English)" accent={t.accent}>
            <View style={[styles.verdictBox, { backgroundColor: t.accentLight }]}>
              <Text style={[styles.bodyText, { color: t.text }]}>{r.investor_verdict}</Text>
            </View>
          </Card>
        )}

        {/* Key Metrics */}
        {r.key_metrics && r.key_metrics.length > 0 && (
          <Card title="📊 Key Financial Metrics">
            <View style={[styles.metricsHeader, { borderBottomColor: t.border }]}>
              <Text style={[styles.metricsHeaderText, { color: t.textSecondary }]}>Metric</Text>
              <Text style={[styles.metricsHeaderText, { color: t.textSecondary }]}>Current · Previous · Change</Text>
            </View>
            {r.key_metrics.filter((m: any) => m.current && m.current !== 'N/A').map((m: any, i: number) => (
              <MetricRow key={i} metric={m} />
            ))}
          </Card>
        )}

        {/* Profitability */}
        {r.profitability && (
          <Card title="💰 Profitability Analysis">
            <Text style={[styles.bodyText, { color: t.text }]}>{r.profitability.analysis}</Text>
            <View style={styles.statsGrid}>
              <StatBox label="Gross Margin" val={r.profitability.gross_margin_current} prev={r.profitability.gross_margin_previous} />
              <StatBox label="EBITDA Margin" val={r.profitability.ebitda_margin_current} prev={r.profitability.ebitda_margin_previous} />
              <StatBox label="Net Margin" val={r.profitability.net_margin_current} prev={r.profitability.net_margin_previous} />
              <StatBox label="ROE" val={r.profitability.roe} color="#22c55e" />
              <StatBox label="ROA" val={r.profitability.roa} color="#22c55e" />
            </View>
            {r.profitability.key_cost_drivers && r.profitability.key_cost_drivers.length > 0 && (
              <View style={{ marginTop: 12 }}>
                <Text style={[styles.subTitle, { color: t.text }]}>Key Cost Drivers:</Text>
                {r.profitability.key_cost_drivers.map((c: string, i: number) => (
                  <Text key={i} style={[styles.bulletItem, { color: t.textSecondary }]}>• {c}</Text>
                ))}
              </View>
            )}
          </Card>
        )}

        {/* Growth */}
        {r.growth && (
          <Card title="📈 Growth Analysis">
            <Text style={[styles.bodyText, { color: t.text }]}>{r.growth.analysis}</Text>
            <View style={styles.statsGrid}>
              <StatBox label="Revenue Growth YoY" val={r.growth.revenue_growth_yoy} color="#22c55e" />
              <StatBox label="Profit Growth YoY" val={r.growth.profit_growth_yoy} color="#22c55e" />
              {r.growth.volume_growth && r.growth.volume_growth !== 'N/A' && (
                <StatBox label="Volume Growth" val={r.growth.volume_growth} color="#22c55e" />
              )}
            </View>
            {r.chart_data?.revenue_trend && (
              <BarChart
                data={r.chart_data.revenue_trend}
                valueKey="value"
                labelKey="period"
                color={t.accent}
                title="Revenue Trend"
              />
            )}
            {r.growth.guidance && r.growth.guidance !== 'N/A' && (
              <View style={[styles.guidanceBox, { backgroundColor: t.accentLight }]}>
                <Text style={[styles.subTitle, { color: t.text }]}>📌 Management Guidance:</Text>
                <Text style={[styles.bodyText, { color: t.text }]}>{r.growth.guidance}</Text>
              </View>
            )}
          </Card>
        )}

        {/* Liquidity */}
        {r.liquidity && (
          <Card title="💧 Liquidity & Cash Position">
            <Text style={[styles.bodyText, { color: t.text }]}>{r.liquidity.analysis}</Text>
            <View style={styles.statsGrid}>
              <StatBox label="Current Ratio" val={r.liquidity.current_ratio} />
              <StatBox label="Quick Ratio" val={r.liquidity.quick_ratio} />
              <StatBox label="Cash Position" val={r.liquidity.cash_position} />
              <StatBox label="Operating Cash Flow" val={r.liquidity.operating_cash_flow} />
              <StatBox label="Free Cash Flow" val={r.liquidity.free_cash_flow} />
            </View>
          </Card>
        )}

        {/* Debt */}
        {r.debt && (
          <Card title="🏦 Debt & Leverage">
            <Text style={[styles.bodyText, { color: t.text }]}>{r.debt.analysis}</Text>
            <View style={styles.statsGrid}>
              <StatBox label="Total Debt" val={r.debt.total_debt} />
              <StatBox label="Net Debt" val={r.debt.net_debt} />
              <StatBox label="Debt/Equity" val={r.debt.debt_to_equity} />
              <StatBox label="Interest Coverage" val={r.debt.interest_coverage} />
            </View>
            {r.debt.debt_trend && (
              <View style={[styles.trendPill, { backgroundColor: r.debt.debt_trend === 'Decreasing' ? '#22c55e20' : r.debt.debt_trend === 'Increasing' ? '#ef444420' : '#88888820' }]}>
                <Text style={{ color: r.debt.debt_trend === 'Decreasing' ? '#22c55e' : r.debt.debt_trend === 'Increasing' ? '#ef4444' : '#888', fontWeight: '700', fontSize: 13 }}>
                  Debt Trend: {r.debt.debt_trend}
                </Text>
              </View>
            )}
          </Card>
        )}

        {/* Management Commentary */}
        {r.management_commentary && (
          <Card title="🎙️ Management Commentary">
            {r.management_commentary.overall_tone && (
              <View style={[styles.toneBadge, {
                backgroundColor: r.management_commentary.overall_tone === 'Positive' ? '#22c55e20' :
                  r.management_commentary.overall_tone === 'Concerned' ? '#ef444420' : '#f59e0b20'
              }]}>
                <Text style={{
                  fontWeight: '700', fontSize: 13,
                  color: r.management_commentary.overall_tone === 'Positive' ? '#22c55e' :
                    r.management_commentary.overall_tone === 'Concerned' ? '#ef4444' : '#f59e0b'
                }}>Management Tone: {r.management_commentary.overall_tone}</Text>
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
            {r.management_commentary.concerns_raised?.length > 0 && (
              <View style={{ marginTop: 10 }}>
                <Text style={[styles.subTitle, { color: t.text }]}>Concerns Acknowledged:</Text>
                {r.management_commentary.concerns_raised.map((c: string, i: number) => (
                  <Text key={i} style={[styles.bulletItem, { color: '#ef4444' }]}>• {c}</Text>
                ))}
              </View>
            )}
          </Card>
        )}

        {/* Segments */}
        {r.segments && r.segments.length > 0 && (
          <Card title="🏢 Business Segments">
            {r.segments.map((seg: any, i: number) => (
              <View key={i} style={[styles.segmentBox, { backgroundColor: t.cardAlt }]}>
                <Text style={[styles.segmentName, { color: t.text }]}>{seg.name}</Text>
                <View style={styles.segmentStats}>
                  {seg.revenue && <View style={[styles.segmentPill, { backgroundColor: t.accentLight }]}><Text style={{ color: t.accent, fontSize: 11 }}>Rev: {seg.revenue}</Text></View>}
                  {seg.growth && <View style={[styles.segmentPill, { backgroundColor: '#22c55e20' }]}><Text style={{ color: '#22c55e', fontSize: 11 }}>Growth: {seg.growth}</Text></View>}
                  {seg.margin && <View style={[styles.segmentPill, { backgroundColor: '#f59e0b20' }]}><Text style={{ color: '#f59e0b', fontSize: 11 }}>Margin: {seg.margin}</Text></View>}
                </View>
                {seg.comment && <Text style={[styles.metricComment, { color: t.textSecondary }]}>{seg.comment}</Text>}
              </View>
            ))}
          </Card>
        )}

        {/* Highlights */}
        {r.highlights && r.highlights.length > 0 && (
          <Card title="✅ Key Strengths">
            {r.highlights.map((h: string, i: number) => (
              <View key={i} style={styles.bulletRow}>
                <View style={[styles.bulletDotCircle, { backgroundColor: '#22c55e20' }]}>
                  <Text style={{ color: '#22c55e', fontSize: 10 }}>✓</Text>
                </View>
                <Text style={[styles.bulletText, { color: t.text }]}>{h}</Text>
              </View>
            ))}
          </Card>
        )}

        {/* Risks */}
        {r.risks && r.risks.length > 0 && (
          <Card title="⚠️ Key Risks">
            {r.risks.map((risk: string, i: number) => (
              <View key={i} style={styles.bulletRow}>
                <View style={[styles.bulletDotCircle, { backgroundColor: '#ef444420' }]}>
                  <Text style={{ color: '#ef4444', fontSize: 10 }}>!</Text>
                </View>
                <Text style={[styles.bulletText, { color: t.text }]}>{risk}</Text>
              </View>
            ))}
          </Card>
        )}

        {/* What to Watch */}
        {r.what_to_watch && r.what_to_watch.length > 0 && (
          <Card title="🔭 What to Watch Next">
            {r.what_to_watch.map((w: string, i: number) => (
              <View key={i} style={styles.bulletRow}>
                <View style={[styles.bulletDotCircle, { backgroundColor: t.accentLight }]}>
                  <Text style={{ color: t.accent, fontSize: 10 }}>→</Text>
                </View>
                <Text style={[styles.bulletText, { color: t.text }]}>{w}</Text>
              </View>
            ))}
          </Card>
        )}

        <TouchableOpacity style={[styles.btn, { backgroundColor: t.accent }]} onPress={() => router.back()}>
          <Text style={styles.btnText}>Back to Home</Text>
        </TouchableOpacity>
        <View style={{ height: 40 }} />
      </ScrollView>
    </ThemeContext.Provider>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  loadingText: { marginTop: 12, fontSize: 16 },
  errorText: { color: '#ef4444', fontSize: 16, textAlign: 'center', marginBottom: 16 },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, marginTop: 8 },
  backText: { fontSize: 16, fontWeight: '600' },
  themeToggle: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  themeLabel: { fontSize: 18 },
  header: { marginBottom: 20 },
  company: { fontSize: 26, fontWeight: '800', letterSpacing: -0.5 },
  period: { fontSize: 13, marginTop: 4 },
  currency: { fontSize: 12, marginTop: 2 },
  scoreCard: { borderRadius: 24, padding: 24, alignItems: 'center', marginBottom: 16, shadowColor: '#000', shadowOpacity: 0.08, shadowRadius: 16, elevation: 4 },
  scoreLabel: { fontSize: 12, fontWeight: '600', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 8 },
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
  trendPill: { borderRadius: 8, padding: 10, marginTop: 10, alignSelf: 'flex-start' },
  toneBadge: { borderRadius: 8, padding: 10, marginBottom: 8, alignSelf: 'flex-start' },
  bulletRow: { flexDirection: 'row', marginBottom: 10, alignItems: 'flex-start' },
  bulletDotCircle: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center', marginRight: 10, marginTop: 2, flexShrink: 0 },
  bulletText: { fontSize: 14, lineHeight: 22, flex: 1 },
  bulletItem: { fontSize: 13, lineHeight: 22, marginBottom: 4 },
  segmentBox: { borderRadius: 10, padding: 12, marginBottom: 8 },
  segmentName: { fontSize: 14, fontWeight: '700', marginBottom: 6 },
  segmentStats: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 6 },
  segmentPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  metricComment: { fontSize: 11, marginTop: 2, fontStyle: 'italic' },
  btn: { borderRadius: 14, padding: 16, alignItems: 'center', marginTop: 8 },
  btnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
});
