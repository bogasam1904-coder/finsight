import React, { useEffect, useState, useContext, createContext, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Dimensions, Switch, Share, Platform, Alert
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../../src/api';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';

const ThemeContext = createContext({ dark: false, toggle: () => {} });
const { width } = Dimensions.get('window');

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
              <View style={[styles.progressBarFill, { width: `${pct}%`, backgroundColor: barColor }]} />
            </View>
            <Text style={{ fontSize: 12, color: t.textSecondary, marginTop: 6, lineHeight: 18 }}>{c.reasoning}</Text>
          </View>
        );
      })}
    </View>
  );
};

export default function AnalysisScreen() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dark, setDark] = useState(false);
  const [downloading, setDownloading] = useState(false);
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

  const generateHTML = (r: any) => {
    const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';
    const metricRows = (r.key_metrics || []).filter((m: any) => m.current && m.current !== 'N/A').map((m: any) => `
      <tr>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;font-size:13px;color:#333">${m.label}<br/><span style="font-size:11px;color:#999;font-style:italic">${m.comment || ''}</span></td>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;font-size:13px;font-weight:700;text-align:right">${m.current}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;font-size:12px;color:#888;text-align:right">${m.previous || '-'}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;font-size:12px;font-weight:600;text-align:right;color:${m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : '#888'}">${m.change || '-'}</td>
      </tr>`).join('');

    const scoreRows = (r.health_score_breakdown?.components || []).map((c: any) => {
      const color = c.rating === 'Strong' ? '#22c55e' : c.rating === 'Moderate' ? '#f59e0b' : '#ef4444';
      const pct = c.max > 0 ? Math.round((c.score / c.max) * 100) : 0;
      return `
        <div style="background:#f8faff;border-radius:10px;padding:14px;margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-weight:700;font-size:14px">${c.category}</span>
            <span style="font-weight:700;color:${color}">${c.score}/${c.max} — ${c.rating}</span>
          </div>
          <div style="background:#e5e7eb;border-radius:4px;height:6px;margin-bottom:8px">
            <div style="background:${color};height:6px;border-radius:4px;width:${pct}%"></div>
          </div>
          <p style="margin:0;font-size:12px;color:#555;line-height:1.6">${c.reasoning}</p>
        </div>`;
    }).join('');

    const highlights = (r.highlights || []).map((h: string) => `<li style="margin-bottom:6px;font-size:13px;color:#333">${h}</li>`).join('');
    const risks = (r.risks || []).map((risk: string) => `<li style="margin-bottom:6px;font-size:13px;color:#333">${risk}</li>`).join('');
    const watches = (r.what_to_watch || []).map((w: string) => `<li style="margin-bottom:6px;font-size:13px;color:#333">${w}</li>`).join('');
    const mgmtPoints = (r.management_commentary?.key_points || []).map((p: string) => `<li style="margin-bottom:6px;font-size:13px">${p}</li>`).join('');
    const segments = (r.segments || []).filter((s: any) => s.name).map((s: any) => `
      <div style="background:#f8faff;border-radius:8px;padding:12px;margin-bottom:8px">
        <strong style="font-size:14px">${s.name}</strong>
        <div style="display:flex;gap:10px;margin-top:6px;flex-wrap:wrap">
          ${s.revenue ? `<span style="background:#eef4ff;color:#0052ff;padding:3px 8px;border-radius:4px;font-size:11px">Rev: ${s.revenue}</span>` : ''}
          ${s.growth ? `<span style="background:#f0fdf4;color:#22c55e;padding:3px 8px;border-radius:4px;font-size:11px">Growth: ${s.growth}</span>` : ''}
          ${s.margin ? `<span style="background:#fffbeb;color:#f59e0b;padding:3px 8px;border-radius:4px;font-size:11px">Margin: ${s.margin}</span>` : ''}
        </div>
        ${s.comment ? `<p style="margin:6px 0 0;font-size:12px;color:#666">${s.comment}</p>` : ''}
      </div>`).join('');

    return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #fff; color: #0a0e1a; }
  .page { max-width: 800px; margin: 0 auto; padding: 32px; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; padding-bottom: 20px; border-bottom: 2px solid #0052ff; }
  .logo { font-size: 22px; font-weight: 900; color: #0052ff; }
  .logo span { font-size: 14px; }
  .company { font-size: 28px; font-weight: 800; margin: 0 0 4px; }
  .period { font-size: 14px; color: #666; }
  .score-card { text-align: center; background: linear-gradient(135deg, #f0f4ff, #fff); border: 2px solid #e5e7eb; border-radius: 20px; padding: 32px; margin-bottom: 24px; }
  .score-num { font-size: 80px; font-weight: 900; color: ${scoreColor}; line-height: 1; }
  .score-label { font-size: 20px; font-weight: 700; color: ${scoreColor}; margin-top: 4px; }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid #f0f4ff; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #f8faff; padding: 10px 8px; font-size: 12px; color: #888; text-align: left; text-transform: uppercase; letter-spacing: 0.5px; }
  .verdict { background: #eef4ff; border-left: 4px solid #0052ff; padding: 16px; border-radius: 0 10px 10px 0; font-size: 14px; line-height: 1.7; }
  .footer { text-align: center; color: #999; font-size: 11px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
  ul { padding-left: 18px; margin: 0; }
  li { margin-bottom: 6px; font-size: 13px; }
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <div class="logo">📊 FinSight<br/><span style="color:#888;font-weight:400">AI Financial Analysis</span></div>
    </div>
    <div style="text-align:right">
      <div class="company">${r.company_name || 'Financial Analysis'}</div>
      <div class="period">${r.statement_type || ''} · ${r.period || ''} · ${r.currency || ''}</div>
      <div style="font-size:12px;color:#999;margin-top:4px">Generated on ${new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })}</div>
    </div>
  </div>

  <div class="score-card">
    <div style="font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Financial Health Score</div>
    <div class="score-num">${r.health_score}<span style="font-size:32px;color:#888">/100</span></div>
    <div class="score-label">${r.health_label}</div>
  </div>

  ${r.health_score_breakdown?.components ? `
  <div class="section">
    <div class="section-title">📐 Score Derivation</div>
    ${scoreRows}
  </div>` : ''}

  <div class="section">
    <div class="section-title">📋 Executive Summary</div>
    <p style="font-size:14px;line-height:1.8;color:#333;margin:0">${r.executive_summary || ''}</p>
  </div>

  ${r.investor_verdict ? `
  <div class="section">
    <div class="section-title">💡 Plain English Verdict</div>
    <div class="verdict">${r.investor_verdict}</div>
  </div>` : ''}

  ${metricRows ? `
  <div class="section">
    <div class="section-title">📊 Key Financial Metrics</div>
    <table>
      <tr>
        <th>Metric</th><th style="text-align:right">Current</th><th style="text-align:right">Previous</th><th style="text-align:right">Change</th>
      </tr>
      ${metricRows}
    </table>
  </div>` : ''}

  ${r.profitability ? `
  <div class="section">
    <div class="section-title">💰 Profitability Analysis</div>
    <p style="font-size:14px;line-height:1.8;color:#333;margin:0 0 12px">${r.profitability.analysis || ''}</p>
    ${r.profitability.key_cost_drivers?.length ? `<strong style="font-size:13px">Key Cost Drivers:</strong><ul style="margin-top:6px">${(r.profitability.key_cost_drivers || []).map((c: string) => `<li>${c}</li>`).join('')}</ul>` : ''}
  </div>` : ''}

  ${r.growth ? `
  <div class="section">
    <div class="section-title">📈 Growth Analysis</div>
    <p style="font-size:14px;line-height:1.8;color:#333;margin:0 0 12px">${r.growth.analysis || ''}</p>
    ${r.growth.guidance && r.growth.guidance !== 'N/A' ? `<div style="background:#f0f9ff;border-radius:8px;padding:12px"><strong>Management Guidance:</strong><br/><span style="font-size:13px">${r.growth.guidance}</span></div>` : ''}
  </div>` : ''}

  ${r.debt ? `
  <div class="section">
    <div class="section-title">🏦 Debt & Leverage</div>
    <p style="font-size:14px;line-height:1.8;color:#333;margin:0">${r.debt.analysis || ''}</p>
  </div>` : ''}

  ${r.management_commentary ? `
  <div class="section">
    <div class="section-title">🎙️ Management Commentary</div>
    ${r.management_commentary.overall_tone ? `<div style="margin-bottom:10px"><strong>Overall Tone:</strong> <span style="color:${r.management_commentary.overall_tone === 'Positive' ? '#22c55e' : '#f59e0b'}">${r.management_commentary.overall_tone}</span></div>` : ''}
    ${mgmtPoints ? `<strong style="font-size:13px">Key Points:</strong><ul style="margin-top:6px">${mgmtPoints}</ul>` : ''}
    ${r.management_commentary.outlook_statement && r.management_commentary.outlook_statement !== 'N/A' ? `<div style="background:#f0f9ff;border-radius:8px;padding:12px;margin-top:10px"><strong>Outlook:</strong><br/><span style="font-size:13px">${r.management_commentary.outlook_statement}</span></div>` : ''}
  </div>` : ''}

  ${segments ? `
  <div class="section">
    <div class="section-title">🏢 Business Segments</div>
    ${segments}
  </div>` : ''}

  ${highlights ? `
  <div class="section">
    <div class="section-title">✅ Key Strengths</div>
    <ul>${highlights}</ul>
  </div>` : ''}

  ${risks ? `
  <div class="section">
    <div class="section-title">⚠️ Key Risks</div>
    <ul>${risks}</ul>
  </div>` : ''}

  ${watches ? `
  <div class="section">
    <div class="section-title">🔭 What to Watch Next</div>
    <ul>${watches}</ul>
  </div>` : ''}

  <div class="footer">
    Generated by FinSight · AI-Powered Financial Analysis · finsight-vert.vercel.app<br/>
    This report is for informational purposes only and does not constitute financial advice.
  </div>
</div>
</body>
</html>`;
  };

  const handleDownloadPDF = async () => {
    if (!analysis?.result) return;
    setDownloading(true);
    try {
      const html = generateHTML(analysis.result);
      const { uri } = await Print.printToFileAsync({ html, base64: false });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, {
          mimeType: 'application/pdf',
          dialogTitle: `${analysis.result.company_name || 'FinSight'} Analysis`,
          UTI: 'com.adobe.pdf'
        });
      } else {
        Alert.alert('PDF Ready', 'PDF has been generated successfully!');
      }
    } catch (e) {
      Alert.alert('Error', 'Failed to generate PDF. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  const handleShare = async () => {
    if (!analysis?.result) return;
    const r = analysis.result;
    const shareUrl = `https://finsight-vert.vercel.app/analysis/${id}`;
    const message = `📊 FinSight Analysis: ${r.company_name}\n\n` +
      `Period: ${r.period}\n` +
      `Health Score: ${r.health_score}/100 (${r.health_label})\n\n` +
      `${r.investor_verdict?.substring(0, 200) || ''}...\n\n` +
      `View full analysis: ${shareUrl}`;
    try {
      await Share.share({
        message,
        url: shareUrl,
        title: `${r.company_name} Financial Analysis — FinSight`,
      });
    } catch (e) {
      Alert.alert('Error', 'Failed to share. Please try again.');
    }
  };

  const handleCopyLink = async () => {
    const shareUrl = `https://finsight-vert.vercel.app/analysis/${id}`;
    try {
      if (Platform.OS === 'web') {
        await navigator.clipboard.writeText(shareUrl);
        Alert.alert('✅ Copied!', 'Link copied to clipboard.');
      } else {
        await Share.share({ message: shareUrl });
      }
    } catch (e) {
      Alert.alert('Link', `Share this link:\n${shareUrl}`);
    }
  };

  if (loading) return (
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={[styles.loadingText, { color: t.textSecondary }]}>Preparing analysis...</Text>
    </View>
  );

  if (error || !analysis || !analysis.result) return (
    <View style={[styles.center, { backgroundColor: t.bg }]}>
      <Text style={styles.errorText}>No results found</Text>
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
            <Text style={{ fontSize: 16 }}>{dark ? '🌙' : '☀️'}</Text>
            <Switch value={dark} onValueChange={setDark}
              trackColor={{ false: '#CBD5E1', true: '#4F8AFF' }}
              thumbColor='#fff' />
          </View>
        </View>

        {/* Header */}
        <View style={styles.header}>
          <Text style={[styles.company, { color: t.text }]}>{r.company_name || 'Financial Analysis'}</Text>
          <Text style={[styles.period, { color: t.textSecondary }]}>{r.statement_type} · {r.period}</Text>
          <Text style={[styles.currency, { color: t.textSecondary }]}>{r.currency}</Text>
        </View>

        {/* Action Buttons */}
        <View style={styles.actionRow}>
          <TouchableOpacity
            style={[styles.actionBtn, { backgroundColor: t.accent }]}
            onPress={handleDownloadPDF}
            disabled={downloading}
          >
            {downloading
              ? <ActivityIndicator size="small" color="#fff" />
              : <Text style={styles.actionBtnText}>⬇️ Download PDF</Text>
            }
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: '#25D366' }]} onPress={handleShare}>
            <Text style={styles.actionBtnText}>📤 Share</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: t.cardAlt, borderWidth: 1, borderColor: t.border }]} onPress={handleCopyLink}>
            <Text style={[styles.actionBtnText, { color: t.text }]}>🔗 Copy Link</Text>
          </TouchableOpacity>
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

        {/* Profitability */}
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
            {r.profitability.key_cost_drivers?.length > 0 && (
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

        {/* Liquidity */}
        {r.liquidity && (
          <Card title="💧 Liquidity & Cash">
            <Text style={[styles.bodyText, { color: t.text }]}>{r.liquidity.analysis}</Text>
            <View style={styles.statsGrid}>
              <StatBox label="Current Ratio" val={r.liquidity.current_ratio} />
              <StatBox label="Quick Ratio" val={r.liquidity.quick_ratio} />
              <StatBox label="Cash" val={r.liquidity.cash_position} />
              <StatBox label="Operating CF" val={r.liquidity.operating_cash_flow} />
              <StatBox label="Free CF" val={r.liquidity.free_cash_flow} />
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
              <StatBox label="D/E Ratio" val={r.debt.debt_to_equity} />
              <StatBox label="Interest Coverage" val={r.debt.interest_coverage} />
            </View>
            {r.debt.debt_trend && (
              <View style={[styles.trendPill, {
                backgroundColor: r.debt.debt_trend === 'Decreasing' ? '#22c55e20' : r.debt.debt_trend === 'Increasing' ? '#ef444420' : '#88888820'
              }]}>
                <Text style={{ fontWeight: '700', fontSize: 13, color: r.debt.debt_trend === 'Decreasing' ? '#22c55e' : r.debt.debt_trend === 'Increasing' ? '#ef4444' : '#888' }}>
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
                backgroundColor: r.management_commentary.overall_tone === 'Positive' ? '#22c55e20' : r.management_commentary.overall_tone === 'Concerned' ? '#ef444420' : '#f59e0b20'
              }]}>
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
            {r.management_commentary.concerns_raised?.length > 0 && (
              <View style={{ marginTop: 10 }}>
                <Text style={[styles.subTitle, { color: '#ef4444' }]}>Concerns:</Text>
                {r.management_commentary.concerns_raised.map((c: string, i: number) => (
                  <Text key={i} style={[styles.bulletItem, { color: '#ef4444' }]}>• {c}</Text>
                ))}
              </View>
            )}
          </Card>
        )}

        {/* Segments */}
        {r.segments?.length > 0 && (
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
        {r.highlights?.length > 0 && (
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
        {r.risks?.length > 0 && (
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
        {r.what_to_watch?.length > 0 && (
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

        {/* Bottom Action Buttons */}
        <View style={styles.actionRow}>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: t.accent }]} onPress={handleDownloadPDF} disabled={downloading}>
            {downloading ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.actionBtnText}>⬇️ Download PDF</Text>}
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: '#25D366' }]} onPress={handleShare}>
            <Text style={styles.actionBtnText}>📤 Share</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={[styles.btn, { backgroundColor: t.cardAlt, borderWidth: 1, borderColor: t.border }]} onPress={() => router.back()}>
          <Text style={[styles.btnText, { color: t.text }]}>← Back to Home</Text>
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
  header: { marginBottom: 16 },
  company: { fontSize: 24, fontWeight: '800', letterSpacing: -0.5 },
  period: { fontSize: 13, marginTop: 4 },
  currency: { fontSize: 12, marginTop: 2 },
  actionRow: { flexDirection: 'row', gap: 8, marginBottom: 16 },
  actionBtn: { flex: 1, borderRadius: 12, padding: 12, alignItems: 'center', justifyContent: 'center' },
  actionBtnText: { color: '#fff', fontSize: 13, fontWeight: '700' },
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
  btn: { borderRadius: 14, padding: 16, alignItems: 'center', marginTop: 8 },
  btnText: { fontSize: 16, fontWeight: '700' },
});
