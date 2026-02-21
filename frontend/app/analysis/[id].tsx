import React, { useEffect, useState, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Switch, Share, Platform, Alert, Linking, Animated, StatusBar
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const T = {
  light: {
    bg: '#F4F7FF', card: '#FFFFFF', cardAlt: '#F0F4FF',
    text: '#0A0E1A', textSub: '#6B7280', border: '#E5E7EB',
    accent: '#0052FF', accentBg: '#EEF4FF', accentText: '#0052FF',
    score: { bg: '#F8FAFF', border: '#E5E7EB' },
    tag: { bg: '#EEF4FF', text: '#0052FF' },
    metric: { bg: '#F8FAFF' },
  },
  dark: {
    bg: '#060B18', card: '#0D1426', cardAlt: '#111B35',
    text: '#F0F4FF', textSub: '#6B82A8', border: '#1E2D4A',
    accent: '#4F8AFF', accentBg: '#0D1D3A', accentText: '#4F8AFF',
    score: { bg: '#0D1426', border: '#1E2D4A' },
    tag: { bg: '#0D1D3A', text: '#4F8AFF' },
    metric: { bg: '#0D1426' },
  }
};

function generatePDFHTML(r: any, dark: boolean): string {
  const t = dark ? T.dark : T.light;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';

  const metricRows = (r.key_metrics || [])
    .filter((m: any) => m.current && m.current !== 'N/A')
    .map((m: any) => `
      <tr>
        <td style="padding:10px 12px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#eee'};color:${dark ? '#b0c0e0' : '#333'};font-size:13px">
          ${m.label}<br/>
          <span style="font-size:11px;color:${dark ? '#6B82A8' : '#999'};font-style:italic">${m.comment || ''}</span>
        </td>
        <td style="padding:10px 12px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#eee'};font-weight:700;text-align:right;color:${dark ? '#F0F4FF' : '#0A0E1A'}">${m.current}</td>
        <td style="padding:10px 12px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#eee'};text-align:right;color:${dark ? '#6B82A8' : '#888'};font-size:12px">${m.previous || '—'}</td>
        <td style="padding:10px 12px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#eee'};text-align:right;font-weight:600;font-size:12px;color:${m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : '#888'}">${m.change || '—'}</td>
      </tr>`).join('');

  const scoreRows = (r.health_score_breakdown?.components || []).map((c: any) => {
    const col = c.rating === 'Strong' ? '#22c55e' : c.rating === 'Moderate' ? '#f59e0b' : '#ef4444';
    const pct = c.max > 0 ? Math.round((c.score / c.max) * 100) : 0;
    return `<div style="background:${dark ? '#111B35' : '#f8faff'};border-radius:10px;padding:14px;margin-bottom:10px;border:1px solid ${dark ? '#1E2D4A' : '#e5e7eb'}">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <span style="font-weight:700;font-size:14px;color:${dark ? '#F0F4FF' : '#0A0E1A'}">${c.category}</span>
        <span style="font-weight:700;color:${col}">${c.score}/${c.max} — ${c.rating}</span>
      </div>
      <div style="background:${dark ? '#1E2D4A' : '#e5e7eb'};border-radius:4px;height:6px;margin-bottom:8px">
        <div style="background:${col};height:6px;border-radius:4px;width:${pct}%"></div>
      </div>
      <p style="margin:0;font-size:12px;color:${dark ? '#6B82A8' : '#555'};line-height:1.6">${c.reasoning}</p>
    </div>`;
  }).join('');

  const li = (arr: string[]) => (arr || []).map(x => `<li style="margin-bottom:6px;font-size:13px;color:${dark ? '#b0c0e0' : '#333'};line-height:1.6">${x}</li>`).join('');

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,'Segoe UI',Helvetica,sans-serif;background:${dark ? '#060B18' : '#fff'};color:${dark ? '#F0F4FF' : '#0A0E1A'};-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{max-width:820px;margin:0 auto;padding:40px}
  .header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px;padding-bottom:24px;border-bottom:2px solid ${dark ? '#4F8AFF' : '#0052FF'}}
  .logo{font-size:22px;font-weight:900;color:${dark ? '#4F8AFF' : '#0052FF'};letter-spacing:-0.5px}
  .section{margin-bottom:28px;page-break-inside:avoid}
  .section-title{font-size:15px;font-weight:700;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#f0f0f0'};color:${dark ? '#F0F4FF' : '#0A0E1A'}}
  table{width:100%;border-collapse:collapse}
  th{background:${dark ? '#111B35' : '#f8faff'};padding:8px 12px;font-size:11px;color:${dark ? '#6B82A8' : '#888'};text-align:left;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid ${dark ? '#1E2D4A' : '#eee'}}
  .verdict-box{background:${dark ? '#0D1D3A' : '#eef4ff'};border-left:3px solid ${dark ? '#4F8AFF' : '#0052FF'};padding:14px 18px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;color:${dark ? '#b0c0e0' : '#333'}}
  .footer{text-align:center;color:${dark ? '#3A5080' : '#999'};font-size:11px;margin-top:40px;padding-top:20px;border-top:1px solid ${dark ? '#1E2D4A' : '#eee'}}
  ul{padding-left:20px;margin:8px 0}
  @page{margin:0.5in}
</style></head>
<body><div class="page">
  <div class="header">
    <div>
      <div class="logo">📊 FinSight</div>
      <div style="font-size:12px;color:${dark ? '#6B82A8' : '#888'};margin-top:4px;font-weight:400">AI Financial Analysis Report</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:22px;font-weight:800;letter-spacing:-0.5px">${r.company_name || 'Analysis'}</div>
      <div style="font-size:13px;color:${dark ? '#6B82A8' : '#666'};margin-top:4px">${r.statement_type || ''} · ${r.period || ''} · ${r.currency || ''}</div>
      <div style="font-size:11px;color:${dark ? '#3A5080' : '#999'};margin-top:4px">Generated ${new Date().toLocaleDateString('en-IN',{day:'numeric',month:'long',year:'numeric'})}</div>
    </div>
  </div>

  <div style="text-align:center;background:${dark ? '#0D1426' : '#f4f7ff'};border-radius:20px;padding:32px;margin-bottom:28px;border:1px solid ${dark ? '#1E2D4A' : '#e5e7eb'}">
    <div style="font-size:12px;color:${dark ? '#6B82A8' : '#888'};text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">Financial Health Score</div>
    <div style="font-size:80px;font-weight:900;color:${scoreColor};line-height:1;letter-spacing:-3px">${r.health_score}<span style="font-size:32px;color:${dark ? '#3A5080' : '#ccc'}">/100</span></div>
    <div style="display:inline-block;background:${scoreColor}25;color:${scoreColor};font-weight:700;font-size:18px;padding:6px 20px;border-radius:30px;margin-top:12px">${r.health_label}</div>
  </div>

  ${scoreRows ? `<div class="section"><div class="section-title">📐 Score Derivation</div>${scoreRows}</div>` : ''}
  
  <div class="section">
    <div class="section-title">📋 Executive Summary</div>
    <p style="font-size:14px;line-height:1.9;color:${dark ? '#b0c0e0' : '#333'}">${r.executive_summary || ''}</p>
  </div>

  ${r.investor_verdict ? `<div class="section"><div class="section-title">💡 Plain English Verdict</div><div class="verdict-box">${r.investor_verdict}</div></div>` : ''}

  ${metricRows ? `<div class="section"><div class="section-title">📊 Key Financial Metrics</div><table><tr><th>Metric</th><th style="text-align:right">Current</th><th style="text-align:right">Previous</th><th style="text-align:right">Change</th></tr>${metricRows}</table></div>` : ''}

  ${r.profitability?.analysis ? `<div class="section"><div class="section-title">💰 Profitability</div><p style="font-size:13px;line-height:1.8;color:${dark?'#b0c0e0':'#333'};margin-bottom:10px">${r.profitability.analysis}</p>${r.profitability.key_cost_drivers?.length ? `<strong style="font-size:12px;color:${dark?'#F0F4FF':'#0A0E1A'}">Cost Drivers:</strong><ul style="margin-top:6px">${li(r.profitability.key_cost_drivers)}</ul>` : ''}</div>` : ''}

  ${r.growth?.analysis ? `<div class="section"><div class="section-title">📈 Growth</div><p style="font-size:13px;line-height:1.8;color:${dark?'#b0c0e0':'#333'};margin-bottom:10px">${r.growth.analysis}</p>${r.growth.guidance && r.growth.guidance!=='N/A' ? `<div style="background:${dark?'#0D1D3A':'#f0f9ff'};border-radius:8px;padding:12px;font-size:13px;color:${dark?'#b0c0e0':'#333'}"><strong>Management Guidance:</strong> ${r.growth.guidance}</div>` : ''}</div>` : ''}

  ${r.liquidity?.analysis ? `<div class="section"><div class="section-title">💧 Liquidity & Cash</div><p style="font-size:13px;line-height:1.8;color:${dark?'#b0c0e0':'#333'}">${r.liquidity.analysis}</p></div>` : ''}

  ${r.debt?.analysis ? `<div class="section"><div class="section-title">🏦 Debt & Leverage</div><p style="font-size:13px;line-height:1.8;color:${dark?'#b0c0e0':'#333'}">${r.debt.analysis}</p></div>` : ''}

  ${r.management_commentary ? `<div class="section"><div class="section-title">🎙️ Management Commentary</div>${r.management_commentary.overall_tone ? `<p style="margin-bottom:10px;font-size:13px"><strong>Tone:</strong> <span style="color:${r.management_commentary.overall_tone==='Positive'?'#22c55e':r.management_commentary.overall_tone==='Concerned'?'#ef4444':'#f59e0b'}">${r.management_commentary.overall_tone}</span></p>` : ''}${r.management_commentary.key_points?.length ? `<strong style="font-size:12px">Key Points:</strong><ul style="margin-top:6px">${li(r.management_commentary.key_points)}</ul>` : ''}${r.management_commentary.outlook_statement && r.management_commentary.outlook_statement!=='N/A' ? `<div style="background:${dark?'#0D1D3A':'#f0f9ff'};border-radius:8px;padding:12px;margin-top:10px;font-size:13px;color:${dark?'#b0c0e0':'#333'}"><strong>Outlook:</strong> ${r.management_commentary.outlook_statement}</div>` : ''}</div>` : ''}

  ${r.highlights?.length ? `<div class="section"><div class="section-title">✅ Key Strengths</div><ul>${li(r.highlights)}</ul></div>` : ''}
  ${r.risks?.length ? `<div class="section"><div class="section-title">⚠️ Key Risks</div><ul>${li(r.risks)}</ul></div>` : ''}
  ${r.what_to_watch?.length ? `<div class="section"><div class="section-title">🔭 What to Watch</div><ul>${li(r.what_to_watch)}</ul></div>` : ''}

  <div class="footer">
    Generated by FinSight · AI-Powered Financial Analysis · finsight-vert.vercel.app<br/>
    For informational purposes only. Not financial advice. · ${dark ? 'Dark' : 'Light'} Theme
  </div>
</div></body></html>`;
}

export default function AnalysisScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const t = dark ? T.dark : T.light;

  useEffect(() => {
    fetchAnalysis();
  }, [id]);

  const fetchAnalysis = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const res = await fetch(`${BACKEND}/api/analyses/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Not found');
      const data = await res.json();
      setAnalysis(data);
      Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: true }).start();
    } catch {
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  };

  // INSTANT PDF DOWNLOAD — opens new window with HTML formatted to save as PDF
  const handleDownloadPDF = async () => {
    if (!analysis?.result) return;
    setDownloading(true);
    try {
      const html = generatePDFHTML(analysis.result, dark);
      const filename = `${(analysis.result.company_name || 'FinSight').replace(/[^a-z0-9]/gi, '_')}_Analysis`;

      if (Platform.OS === 'web') {
        // Open in new tab — user just presses Ctrl+P / Cmd+P and saves as PDF
        // We inject auto-print so it opens the save dialog immediately
        const fullHTML = `<!DOCTYPE html><html><head><title>${filename}</title>
<script>window.onload=function(){setTimeout(function(){window.print()},500)}<\/script>
<style>@media print{@page{margin:0.4in} body{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style>
</head><body>${html.replace(/<!DOCTYPE html>[\s\S]*?<body>/, '').replace(/<\/body>[\s\S]*?<\/html>/, '')}</body></html>`;
        const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${filename}.html`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        Alert.alert('Downloaded!', 'Open the downloaded HTML file and press Ctrl+P (Cmd+P on Mac) → Save as PDF');
      } else {
        // Mobile — use expo-print
        const { Print, Sharing } = await Promise.all([
          import('expo-print'),
          import('expo-sharing')
        ]).then(([p, s]) => ({ Print: p, Sharing: s }));
        const { uri } = await Print.printToFileAsync({ html, base64: false });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(uri, {
            mimeType: 'application/pdf',
            dialogTitle: `Save ${filename}.pdf`,
            UTI: 'com.adobe.pdf'
          });
        }
      }
    } catch (e) {
      Alert.alert('Error', 'Could not generate PDF');
    } finally {
      setDownloading(false);
    }
  };

  const shareUrl = `https://finsight-vert.vercel.app/share/${id}`;

  const getShareMessage = () => {
    const r = analysis?.result;
    if (!r) return '';
    return `📊 FinSight Analysis: ${r.company_name}\n\nPeriod: ${r.period}\nHealth Score: ${r.health_score}/100 (${r.health_label})\n\n${r.investor_verdict?.substring(0, 180) || ''}...\n\nView full analysis 👇\n${shareUrl}`;
  };

  const handleCopyLink = async () => {
    try {
      if (Platform.OS === 'web' && navigator?.clipboard) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        await Share.share({ message: shareUrl });
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch { Alert.alert('Copied!', shareUrl); }
  };

  const handleWhatsApp = async () => {
    const url = `https://wa.me/?text=${encodeURIComponent(getShareMessage())}`;
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { await Linking.openURL(url).catch(() => Linking.openURL(url)); }
  };

  const handleTwitter = async () => {
    const r = analysis?.result;
    const text = `📊 ${r?.company_name} — Health Score: ${r?.health_score}/100 (${r?.health_label})\n\nAnalysed by FinSight — AI Financial Analysis`;
    const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(shareUrl)}`;
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { await Linking.openURL(url); }
  };

  const handleMoreShare = async () => {
    try {
      await Share.share({ message: getShareMessage(), title: `${analysis?.result?.company_name} — FinSight` });
    } catch { }
  };

  const handleBack = () => {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace('/(tabs)');
    }
  };

  if (loading) return (
    <View style={[s.center, { backgroundColor: t.bg }]}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={[s.loadingText, { color: t.textSub }]}>Loading analysis...</Text>
    </View>
  );

  if (!analysis?.result) return (
    <View style={[s.center, { backgroundColor: t.bg }]}>
      <Text style={{ fontSize: 48, marginBottom: 16 }}>📄</Text>
      <Text style={[s.errorTitle, { color: t.text }]}>Analysis not found</Text>
      <TouchableOpacity style={[s.btn, { backgroundColor: t.accent }]} onPress={handleBack}>
        <Text style={s.btnText}>← Go Back</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const scoreColor = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : r.health_score >= 40 ? '#ef4444' : '#dc2626';

  const Card = ({ title, children, leftBorder }: any) => (
    <View style={[s.card, { backgroundColor: t.card, borderColor: t.border, borderLeftColor: leftBorder || t.border, borderLeftWidth: leftBorder ? 3 : 1 }]}>
      {title && <Text style={[s.cardTitle, { color: t.text }]}>{title}</Text>}
      {children}
    </View>
  );

  const MetricRow = ({ m }: any) => {
    if (!m.current || m.current === 'N/A') return null;
    const tc = m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : t.textSub;
    const ti = m.trend === 'up' ? '▲' : m.trend === 'down' ? '▼' : '—';
    return (
      <View style={[s.metricRow, { borderBottomColor: t.border }]}>
        <View style={s.metricLeft}>
          <Text style={[s.metricLabel, { color: t.text }]}>{m.label}</Text>
          {m.comment && m.comment !== 'N/A' && <Text style={[s.metricNote, { color: t.textSub }]}>{m.comment}</Text>}
        </View>
        <View style={s.metricRight}>
          <Text style={[s.metricVal, { color: t.text }]}>{m.current}</Text>
          {m.previous && m.previous !== 'N/A' && <Text style={[s.metricPrev, { color: t.textSub }]}>vs {m.previous}</Text>}
          {m.change && m.change !== 'N/A' && <Text style={[s.metricChange, { color: tc }]}>{ti} {m.change}</Text>}
        </View>
      </View>
    );
  };

  const Stat = ({ label, val, prev, color }: any) => {
    if (!val || val === 'N/A') return null;
    return (
      <View style={[s.stat, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <Text style={[s.statVal, { color: color || t.accent }]}>{val}</Text>
        {prev && prev !== 'N/A' && <Text style={[s.statPrev, { color: t.textSub }]}>vs {prev}</Text>}
        <Text style={[s.statLabel, { color: t.textSub }]}>{label}</Text>
      </View>
    );
  };

  const ScoreBar = ({ c }: any) => {
    const col = c.rating === 'Strong' ? '#22c55e' : c.rating === 'Moderate' ? '#f59e0b' : '#ef4444';
    const pct = c.max > 0 ? (c.score / c.max) * 100 : 0;
    return (
      <View style={[s.scoreBar, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <View style={s.scoreBarTop}>
          <Text style={[s.scoreBarCat, { color: t.text }]}>{c.category}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <View style={[s.ratingPill, { backgroundColor: col + '25' }]}>
              <Text style={[s.ratingText, { color: col }]}>{c.rating}</Text>
            </View>
            <Text style={[s.scoreBarScore, { color: col }]}>{c.score}/{c.max}</Text>
          </View>
        </View>
        <View style={[s.barBg, { backgroundColor: t.border }]}>
          <View style={[s.barFill, { width: `${pct}%` as any, backgroundColor: col }]} />
        </View>
        <Text style={[s.scoreBarReason, { color: t.textSub }]}>{c.reasoning}</Text>
      </View>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Animated.ScrollView style={[s.scroll, { opacity: fadeAnim }]} showsVerticalScrollIndicator={false}>

        {/* Top bar */}
        <View style={[s.topBar, { borderBottomColor: t.border }]}>
          <TouchableOpacity style={s.backBtn} onPress={handleBack}>
            <Text style={[s.backBtnText, { color: t.accent }]}>← Back</Text>
          </TouchableOpacity>
          <View style={s.topBarCenter}>
            <Text style={s.topBarLogo}>📊</Text>
            <Text style={[s.topBarLogoText, { color: t.accent }]}>FinSight</Text>
          </View>
          <View style={s.themeRow}>
            <Text style={{ fontSize: 14 }}>{dark ? '🌙' : '☀️'}</Text>
            <Switch value={dark} onValueChange={setDark}
              trackColor={{ false: '#CBD5E1', true: t.accent }}
              thumbColor="#fff" style={{ transform: [{ scale: 0.8 }] }} />
          </View>
        </View>

        <View style={s.content}>
          {/* Header */}
          <View style={s.pageHeader}>
            <Text style={[s.companyName, { color: t.text }]}>{r.company_name}</Text>
            <Text style={[s.companyMeta, { color: t.textSub }]}>{r.statement_type} · {r.period} · {r.currency}</Text>
          </View>

          {/* Score Card */}
          <View style={[s.scoreCard, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={[s.scoreCardLabel, { color: t.textSub }]}>FINANCIAL HEALTH SCORE</Text>
            <View style={s.scoreRow}>
              <Text style={[s.scoreNum, { color: scoreColor }]}>{r.health_score}</Text>
              <Text style={[s.scoreDenom, { color: t.textSub }]}>/100</Text>
            </View>
            <View style={[s.scoreLabelPill, { backgroundColor: scoreColor + '20' }]}>
              <Text style={[s.scoreLabelText, { color: scoreColor }]}>{r.health_label}</Text>
            </View>
            {r.health_score_breakdown?.components && (
              <View style={{ width: '100%', marginTop: 20 }}>
                <Text style={[s.cardTitle, { color: t.text, marginBottom: 12 }]}>Score Breakdown</Text>
                {r.health_score_breakdown.components.map((c: any, i: number) => <ScoreBar key={i} c={c} />)}
              </View>
            )}
          </View>

          {/* Executive Summary */}
          <Card title="📋 Executive Summary">
            <Text style={[s.body, { color: t.text }]}>{r.executive_summary}</Text>
          </Card>

          {/* Verdict */}
          {r.investor_verdict && (
            <Card title="💡 Plain English Verdict" leftBorder={t.accent}>
              <View style={[s.verdictBox, { backgroundColor: t.accentBg }]}>
                <Text style={[s.body, { color: t.text }]}>{r.investor_verdict}</Text>
              </View>
            </Card>
          )}

          {/* Metrics */}
          {r.key_metrics?.filter((m: any) => m.current && m.current !== 'N/A').length > 0 && (
            <Card title="📊 Key Financial Metrics">
              <View style={[s.metricsHead, { borderBottomColor: t.border }]}>
                <Text style={[s.metricsHeadText, { color: t.textSub }]}>Metric</Text>
                <Text style={[s.metricsHeadText, { color: t.textSub }]}>Now · Before · Δ</Text>
              </View>
              {r.key_metrics.map((m: any, i: number) => <MetricRow key={i} m={m} />)}
            </Card>
          )}

          {/* Profitability */}
          {r.profitability && (
            <Card title="💰 Profitability">
              <Text style={[s.body, { color: t.text, marginBottom: 14 }]}>{r.profitability.analysis}</Text>
              <View style={s.statsGrid}>
                <Stat label="Gross Margin" val={r.profitability.gross_margin_current} prev={r.profitability.gross_margin_previous} />
                <Stat label="EBITDA Margin" val={r.profitability.ebitda_margin_current} prev={r.profitability.ebitda_margin_previous} />
                <Stat label="Net Margin" val={r.profitability.net_margin_current} prev={r.profitability.net_margin_previous} />
                <Stat label="ROE" val={r.profitability.roe} color="#22c55e" />
                <Stat label="ROA" val={r.profitability.roa} color="#22c55e" />
              </View>
              {r.profitability.key_cost_drivers?.length > 0 && (
                <View style={{ marginTop: 14 }}>
                  <Text style={[s.subhead, { color: t.text }]}>Key Cost Drivers</Text>
                  {r.profitability.key_cost_drivers.map((d: string, i: number) => (
                    <Text key={i} style={[s.bullet, { color: t.textSub }]}>· {d}</Text>
                  ))}
                </View>
              )}
            </Card>
          )}

          {/* Growth */}
          {r.growth && (
            <Card title="📈 Growth">
              <Text style={[s.body, { color: t.text, marginBottom: 14 }]}>{r.growth.analysis}</Text>
              <View style={s.statsGrid}>
                <Stat label="Revenue Growth" val={r.growth.revenue_growth_yoy} color="#22c55e" />
                <Stat label="Profit Growth" val={r.growth.profit_growth_yoy} color="#22c55e" />
              </View>
              {r.growth.guidance && r.growth.guidance !== 'N/A' && (
                <View style={[s.infoBox, { backgroundColor: t.accentBg, marginTop: 14 }]}>
                  <Text style={[s.subhead, { color: t.accentText, marginBottom: 4 }]}>📌 Management Guidance</Text>
                  <Text style={[s.body, { color: t.text }]}>{r.growth.guidance}</Text>
                </View>
              )}
            </Card>
          )}

          {/* Liquidity */}
          {r.liquidity && (
            <Card title="💧 Liquidity & Cash">
              <Text style={[s.body, { color: t.text, marginBottom: 14 }]}>{r.liquidity.analysis}</Text>
              <View style={s.statsGrid}>
                <Stat label="Current Ratio" val={r.liquidity.current_ratio} />
                <Stat label="Quick Ratio" val={r.liquidity.quick_ratio} />
                <Stat label="Cash" val={r.liquidity.cash_position} />
                <Stat label="Operating CF" val={r.liquidity.operating_cash_flow} />
                <Stat label="Free CF" val={r.liquidity.free_cash_flow} />
              </View>
            </Card>
          )}

          {/* Debt */}
          {r.debt && (
            <Card title="🏦 Debt & Leverage">
              <Text style={[s.body, { color: t.text, marginBottom: 14 }]}>{r.debt.analysis}</Text>
              <View style={s.statsGrid}>
                <Stat label="Total Debt" val={r.debt.total_debt} />
                <Stat label="D/E Ratio" val={r.debt.debt_to_equity} />
                <Stat label="Interest Coverage" val={r.debt.interest_coverage} />
                <Stat label="Net Debt" val={r.debt.net_debt} />
              </View>
              {r.debt.debt_trend && (
                <View style={[s.trendPill, { backgroundColor: r.debt.debt_trend === 'Decreasing' ? '#22c55e20' : r.debt.debt_trend === 'Increasing' ? '#ef444420' : t.cardAlt }]}>
                  <Text style={{ color: r.debt.debt_trend === 'Decreasing' ? '#22c55e' : r.debt.debt_trend === 'Increasing' ? '#ef4444' : t.textSub, fontWeight: '700', fontSize: 13 }}>
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
                <View style={[s.tonePill, { backgroundColor: r.management_commentary.overall_tone === 'Positive' ? '#22c55e20' : r.management_commentary.overall_tone === 'Concerned' ? '#ef444420' : '#f59e0b20' }]}>
                  <Text style={{ color: r.management_commentary.overall_tone === 'Positive' ? '#22c55e' : r.management_commentary.overall_tone === 'Concerned' ? '#ef4444' : '#f59e0b', fontWeight: '700' }}>
                    Tone: {r.management_commentary.overall_tone}
                  </Text>
                </View>
              )}
              {r.management_commentary.key_points?.length > 0 && (
                <View style={{ marginTop: 12 }}>
                  <Text style={[s.subhead, { color: t.text }]}>Key Points</Text>
                  {r.management_commentary.key_points.map((p: string, i: number) => (
                    <Text key={i} style={[s.bullet, { color: t.text }]}>· {p}</Text>
                  ))}
                </View>
              )}
              {r.management_commentary.outlook_statement && r.management_commentary.outlook_statement !== 'N/A' && (
                <View style={[s.infoBox, { backgroundColor: t.accentBg, marginTop: 12 }]}>
                  <Text style={[s.subhead, { color: t.accentText, marginBottom: 4 }]}>Outlook</Text>
                  <Text style={[s.body, { color: t.text }]}>{r.management_commentary.outlook_statement}</Text>
                </View>
              )}
              {r.management_commentary.concerns_raised?.length > 0 && (
                <View style={{ marginTop: 12 }}>
                  <Text style={[s.subhead, { color: '#ef4444' }]}>Concerns Raised</Text>
                  {r.management_commentary.concerns_raised.map((c: string, i: number) => (
                    <Text key={i} style={[s.bullet, { color: '#ef4444' }]}>· {c}</Text>
                  ))}
                </View>
              )}
            </Card>
          )}

          {/* Segments */}
          {r.segments?.filter((seg: any) => seg.name).length > 0 && (
            <Card title="🏢 Business Segments">
              {r.segments.filter((seg: any) => seg.name).map((seg: any, i: number) => (
                <View key={i} style={[s.segCard, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
                  <Text style={[s.segName, { color: t.text }]}>{seg.name}</Text>
                  <View style={s.segTags}>
                    {seg.revenue && <View style={[s.segTag, { backgroundColor: t.accentBg }]}><Text style={[s.segTagText, { color: t.accentText }]}>Rev: {seg.revenue}</Text></View>}
                    {seg.growth && <View style={[s.segTag, { backgroundColor: '#22c55e20' }]}><Text style={[s.segTagText, { color: '#22c55e' }]}>↑ {seg.growth}</Text></View>}
                    {seg.margin && <View style={[s.segTag, { backgroundColor: '#f59e0b20' }]}><Text style={[s.segTagText, { color: '#f59e0b' }]}>Margin: {seg.margin}</Text></View>}
                  </View>
                  {seg.comment && <Text style={[s.bullet, { color: t.textSub }]}>{seg.comment}</Text>}
                </View>
              ))}
            </Card>
          )}

          {/* Highlights */}
          {r.highlights?.length > 0 && (
            <Card title="✅ Key Strengths">
              {r.highlights.map((h: string, i: number) => (
                <View key={i} style={s.dotRow}>
                  <View style={[s.dot, { backgroundColor: '#22c55e25' }]}><Text style={{ color: '#22c55e', fontSize: 10, fontWeight: '800' }}>✓</Text></View>
                  <Text style={[s.dotText, { color: t.text }]}>{h}</Text>
                </View>
              ))}
            </Card>
          )}

          {/* Risks */}
          {r.risks?.length > 0 && (
            <Card title="⚠️ Key Risks">
              {r.risks.map((risk: string, i: number) => (
                <View key={i} style={s.dotRow}>
                  <View style={[s.dot, { backgroundColor: '#ef444425' }]}><Text style={{ color: '#ef4444', fontSize: 10, fontWeight: '800' }}>!</Text></View>
                  <Text style={[s.dotText, { color: t.text }]}>{risk}</Text>
                </View>
              ))}
            </Card>
          )}

          {/* What to Watch */}
          {r.what_to_watch?.length > 0 && (
            <Card title="🔭 What to Watch Next">
              {r.what_to_watch.map((w: string, i: number) => (
                <View key={i} style={s.dotRow}>
                  <View style={[s.dot, { backgroundColor: t.accentBg }]}><Text style={{ color: t.accent, fontSize: 10, fontWeight: '800' }}>→</Text></View>
                  <Text style={[s.dotText, { color: t.text }]}>{w}</Text>
                </View>
              ))}
            </Card>
          )}

          {/* ── SAVE & SHARE PANEL ── */}
          <View style={[s.sharePanel, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={[s.sharePanelTitle, { color: t.textSub }]}>SAVE & SHARE</Text>

            {/* PDF Download */}
            <TouchableOpacity
              style={[s.pdfBtn, { backgroundColor: t.accent, opacity: downloading ? 0.7 : 1 }]}
              onPress={handleDownloadPDF}
              disabled={downloading}
            >
              {downloading
                ? <ActivityIndicator color="#fff" />
                : <>
                    <Text style={s.pdfBtnIcon}>⬇️</Text>
                    <View>
                      <Text style={s.pdfBtnText}>Download PDF Report</Text>
                      <Text style={s.pdfBtnSub}>Saves in {dark ? 'dark' : 'light'} theme</Text>
                    </View>
                  </>
              }
            </TouchableOpacity>

            {/* Share buttons row */}
            <View style={s.shareBtns}>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleWhatsApp}>
                <Text style={s.shareBtnIcon}>💬</Text>
                <Text style={s.shareBtnLabel}>WhatsApp</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: '#000' }]} onPress={handleTwitter}>
                <Text style={s.shareBtnIcon}>𝕏</Text>
                <Text style={s.shareBtnLabel}>Twitter</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: '#0052FF' }]} onPress={handleMoreShare}>
                <Text style={s.shareBtnIcon}>📤</Text>
                <Text style={s.shareBtnLabel}>More</Text>
              </TouchableOpacity>
            </View>

            {/* Copy Link */}
            <TouchableOpacity
              style={[s.copyLinkBtn, { borderColor: copied ? '#22c55e' : t.accent, backgroundColor: copied ? '#22c55e15' : t.accentBg }]}
              onPress={handleCopyLink}
            >
              <Text style={[s.copyLinkText, { color: copied ? '#22c55e' : t.accent }]}>
                {copied ? '✅ Link Copied to Clipboard!' : '🔗 Copy Shareable Link'}
              </Text>
              {!copied && <Text style={[s.copyLinkSub, { color: t.textSub }]}>Anyone can open this link — no login needed</Text>}
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={[s.backHomeBtn, { borderColor: t.border }]} onPress={handleBack}>
            <Text style={[s.backHomeBtnText, { color: t.textSub }]}>← Back</Text>
          </TouchableOpacity>

          <View style={{ height: 60 }} />
        </View>
      </Animated.ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  scroll: { flex: 1 },
  content: { paddingHorizontal: 16, paddingBottom: 20 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  loadingText: { marginTop: 14, fontSize: 15 },
  errorTitle: { fontSize: 20, fontWeight: '700', marginBottom: 20 },
  topBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 56, paddingBottom: 16, borderBottomWidth: 1 },
  backBtn: { padding: 4 },
  backBtnText: { fontSize: 15, fontWeight: '600' },
  topBarCenter: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  topBarLogo: { fontSize: 20 },
  topBarLogoText: { fontSize: 17, fontWeight: '900', letterSpacing: -0.5 },
  themeRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  pageHeader: { paddingTop: 20, paddingBottom: 16 },
  companyName: { fontSize: 26, fontWeight: '900', letterSpacing: -0.8 },
  companyMeta: { fontSize: 13, marginTop: 4 },
  scoreCard: { borderRadius: 22, padding: 24, alignItems: 'center', marginBottom: 14, borderWidth: 1, shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 20, elevation: 6 },
  scoreCardLabel: { fontSize: 10, fontWeight: '700', letterSpacing: 2, textTransform: 'uppercase', marginBottom: 10 },
  scoreRow: { flexDirection: 'row', alignItems: 'flex-end' },
  scoreNum: { fontSize: 80, fontWeight: '900', lineHeight: 88, letterSpacing: -4 },
  scoreDenom: { fontSize: 26, fontWeight: '600', marginBottom: 14 },
  scoreLabelPill: { borderRadius: 24, paddingHorizontal: 22, paddingVertical: 7, marginTop: 6 },
  scoreLabelText: { fontSize: 16, fontWeight: '800' },
  scoreBar: { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  scoreBarTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  scoreBarCat: { fontSize: 13, fontWeight: '700' },
  ratingPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  ratingText: { fontSize: 10, fontWeight: '800' },
  scoreBarScore: { fontSize: 13, fontWeight: '800' },
  barBg: { height: 6, borderRadius: 3, overflow: 'hidden', marginBottom: 8 },
  barFill: { height: 6, borderRadius: 3 },
  scoreBarReason: { fontSize: 12, lineHeight: 18 },
  card: { borderRadius: 20, padding: 18, marginBottom: 14, borderWidth: 1, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 12, elevation: 3 },
  cardTitle: { fontSize: 15, fontWeight: '800', marginBottom: 14, letterSpacing: -0.3 },
  body: { fontSize: 14, lineHeight: 23 },
  verdictBox: { borderRadius: 12, padding: 16 },
  subhead: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  bullet: { fontSize: 13, lineHeight: 22, marginBottom: 5 },
  infoBox: { borderRadius: 12, padding: 14 },
  metricsHead: { flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 10, borderBottomWidth: 1, marginBottom: 4 },
  metricsHeadText: { fontSize: 10, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  metricRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 11, borderBottomWidth: 1 },
  metricLeft: { flex: 1, paddingRight: 8 },
  metricLabel: { fontSize: 13, fontWeight: '600' },
  metricNote: { fontSize: 11, marginTop: 2, fontStyle: 'italic' },
  metricRight: { alignItems: 'flex-end', minWidth: 110 },
  metricVal: { fontSize: 14, fontWeight: '800' },
  metricPrev: { fontSize: 11, marginTop: 2 },
  metricChange: { fontSize: 12, marginTop: 3, fontWeight: '700' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  stat: { borderRadius: 14, padding: 14, minWidth: '30%', flex: 1, alignItems: 'center', borderWidth: 1 },
  statVal: { fontSize: 16, fontWeight: '800', letterSpacing: -0.5 },
  statPrev: { fontSize: 10, marginTop: 2 },
  statLabel: { fontSize: 10, marginTop: 5, textAlign: 'center', fontWeight: '600' },
  trendPill: { borderRadius: 10, padding: 10, marginTop: 12, alignSelf: 'flex-start' },
  tonePill: { borderRadius: 10, padding: 10, marginBottom: 10, alignSelf: 'flex-start' },
  dotRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 12 },
  dot: { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1, flexShrink: 0 },
  dotText: { fontSize: 14, lineHeight: 22, flex: 1 },
  segCard: { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  segName: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  segTags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 6 },
  segTag: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  segTagText: { fontSize: 11, fontWeight: '700' },
  sharePanel: { borderRadius: 22, padding: 20, marginBottom: 14, borderWidth: 1 },
  sharePanelTitle: { fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', textAlign: 'center', marginBottom: 16 },
  pdfBtn: { borderRadius: 16, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 14 },
  pdfBtnIcon: { fontSize: 24 },
  pdfBtnText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  pdfBtnSub: { color: 'rgba(255,255,255,0.7)', fontSize: 11, marginTop: 2 },
  shareBtns: { flexDirection: 'row', gap: 10, marginBottom: 12 },
  shareBtn: { flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  shareBtnIcon: { fontSize: 18, marginBottom: 4 },
  shareBtnLabel: { color: '#fff', fontSize: 11, fontWeight: '700' },
  copyLinkBtn: { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1.5 },
  copyLinkText: { fontSize: 15, fontWeight: '700' },
  copyLinkSub: { fontSize: 11, marginTop: 4 },
  backHomeBtn: { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1, marginTop: 4 },
  backHomeBtnText: { fontSize: 14, fontWeight: '600' },
  btn: { borderRadius: 14, padding: 16, paddingHorizontal: 32, marginTop: 16 },
  btnText: { color: '#fff', fontSize: 15, fontWeight: '700' },
});
