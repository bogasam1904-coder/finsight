import React, { useEffect, useState, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Switch, Share, Platform, Alert, Linking, Animated, StatusBar
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const DARK = {
  bg: '#060B18', card: '#0D1426', cardAlt: '#111B35', text: '#F0F4FF',
  textSub: '#6B82A8', border: '#1E2D4A', accent: '#4F8AFF', accentBg: '#0D1D3A',
};
const LIGHT = {
  bg: '#F4F7FF', card: '#FFFFFF', cardAlt: '#F0F4FF', text: '#0A0E1A',
  textSub: '#6B7280', border: '#E5E7EB', accent: '#0052FF', accentBg: '#EEF4FF',
};

function pdfHTML(r: any, dark: boolean): string {
  const sc = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';
  const metricRows = (r.key_metrics || []).filter((m: any) => m.current && m.current !== 'N/A')
    .map((m: any) => `<tr>
      <td style="padding:10px 12px;border-bottom:1px solid ${dark?'#1E2D4A':'#eee'};color:${dark?'#b0c0e0':'#333'};font-size:13px">${m.label}<br/><span style="font-size:11px;color:${dark?'#6B82A8':'#999'}">${m.comment||''}</span></td>
      <td style="padding:10px 12px;border-bottom:1px solid ${dark?'#1E2D4A':'#eee'};font-weight:700;text-align:right;color:${dark?'#F0F4FF':'#0A0E1A'}">${m.current}</td>
      <td style="padding:10px 12px;border-bottom:1px solid ${dark?'#1E2D4A':'#eee'};text-align:right;color:${dark?'#6B82A8':'#888'};font-size:12px">${m.previous||'—'}</td>
      <td style="padding:10px 12px;border-bottom:1px solid ${dark?'#1E2D4A':'#eee'};text-align:right;font-weight:700;font-size:12px;color:${m.trend==='up'?'#22c55e':m.trend==='down'?'#ef4444':'#888'}">${m.change||'—'}</td>
    </tr>`).join('');

  const scoreRows = (r.health_score_breakdown?.components || []).map((c: any) => {
    const col = c.rating === 'Strong' ? '#22c55e' : c.rating === 'Moderate' ? '#f59e0b' : '#ef4444';
    const pct = c.max > 0 ? Math.round((c.score / c.max) * 100) : 0;
    return `<div style="background:${dark?'#111B35':'#f8faff'};border-radius:10px;padding:14px;margin-bottom:10px;border:1px solid ${dark?'#1E2D4A':'#e5e7eb'}">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <span style="font-weight:700;font-size:14px;color:${dark?'#F0F4FF':'#0A0E1A'}">${c.category}</span>
        <span style="font-weight:700;color:${col}">${c.score}/${c.max} — ${c.rating}</span>
      </div>
      <div style="background:${dark?'#1E2D4A':'#e5e7eb'};border-radius:4px;height:6px;margin-bottom:8px">
        <div style="background:${col};height:6px;border-radius:4px;width:${pct}%"></div>
      </div>
      <p style="margin:0;font-size:12px;color:${dark?'#6B82A8':'#555'};line-height:1.6">${c.reasoning}</p>
    </div>`;
  }).join('');

  const li = (arr: string[]) =>
    (arr || []).map(x => `<li style="margin-bottom:6px;font-size:13px;color:${dark?'#b0c0e0':'#333'};line-height:1.6">${x}</li>`).join('');

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,'Segoe UI',sans-serif;background:${dark?'#060B18':'#fff'};color:${dark?'#F0F4FF':'#0A0E1A'};-webkit-print-color-adjust:exact;print-color-adjust:exact}.page{max-width:820px;margin:0 auto;padding:40px}.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px;padding-bottom:24px;border-bottom:2px solid ${dark?'#4F8AFF':'#0052FF'}}.logo{font-size:20px;font-weight:900;color:${dark?'#4F8AFF':'#0052FF'}}.sec{margin-bottom:28px;page-break-inside:avoid}.sec-title{font-size:14px;font-weight:700;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid ${dark?'#1E2D4A':'#f0f0f0'}}table{width:100%;border-collapse:collapse}th{background:${dark?'#111B35':'#f8faff'};padding:8px 12px;font-size:11px;color:${dark?'#6B82A8':'#888'};text-align:left;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid ${dark?'#1E2D4A':'#eee'}}.foot{text-align:center;color:${dark?'#3A5080':'#999'};font-size:11px;margin-top:40px;padding-top:20px;border-top:1px solid ${dark?'#1E2D4A':'#eee'}}ul{padding-left:20px;margin:8px 0}@page{margin:0.5in}</style></head>
<body><div class="page">
  <div class="hdr">
    <div><div class="logo">📊 FinSight</div><div style="font-size:12px;color:${dark?'#6B82A8':'#888'};margin-top:4px">AI Financial Analysis Report</div></div>
    <div style="text-align:right">
      <div style="font-size:20px;font-weight:800">${r.company_name||'Analysis'}</div>
      <div style="font-size:13px;color:${dark?'#6B82A8':'#666'};margin-top:4px">${r.statement_type||''} · ${r.period||''} · ${r.currency||''}</div>
      <div style="font-size:11px;color:${dark?'#3A5080':'#999'};margin-top:4px">Generated ${new Date().toLocaleDateString('en-IN',{day:'numeric',month:'long',year:'numeric'})}</div>
    </div>
  </div>
  <div style="text-align:center;background:${dark?'#0D1426':'#f4f7ff'};border-radius:20px;padding:32px;margin-bottom:28px;border:1px solid ${dark?'#1E2D4A':'#e5e7eb'}">
    <div style="font-size:12px;color:${dark?'#6B82A8':'#888'};text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">Financial Health Score</div>
    <div style="font-size:80px;font-weight:900;color:${sc};line-height:1;letter-spacing:-3px">${r.health_score}<span style="font-size:30px;color:${dark?'#3A5080':'#ccc'}">/100</span></div>
    <div style="display:inline-block;background:${sc}25;color:${sc};font-weight:700;font-size:17px;padding:6px 20px;border-radius:30px;margin-top:12px">${r.health_label}</div>
  </div>
  ${scoreRows ? `<div class="sec"><div class="sec-title">📐 Score Breakdown</div>${scoreRows}</div>` : ''}
  <div class="sec"><div class="sec-title">📋 Executive Summary</div><p style="font-size:14px;line-height:1.9;color:${dark?'#b0c0e0':'#333'}">${r.executive_summary||''}</p></div>
  ${r.investor_verdict ? `<div class="sec"><div class="sec-title">💡 Verdict</div><div style="background:${dark?'#0D1D3A':'#eef4ff'};border-left:3px solid ${dark?'#4F8AFF':'#0052FF'};padding:14px 18px;border-radius:0 10px 10px 0;font-size:13px;line-height:1.8;color:${dark?'#b0c0e0':'#333'}">${r.investor_verdict}</div></div>` : ''}
  ${metricRows ? `<div class="sec"><div class="sec-title">📊 Key Metrics</div><table><tr><th>Metric</th><th style="text-align:right">Current</th><th style="text-align:right">Previous</th><th style="text-align:right">Change</th></tr>${metricRows}</table></div>` : ''}
  ${r.highlights?.length ? `<div class="sec"><div class="sec-title">✅ Strengths</div><ul>${li(r.highlights)}</ul></div>` : ''}
  ${r.risks?.length ? `<div class="sec"><div class="sec-title">⚠️ Risks</div><ul>${li(r.risks)}</ul></div>` : ''}
  ${r.what_to_watch?.length ? `<div class="sec"><div class="sec-title">🔭 Watch</div><ul>${li(r.what_to_watch)}</ul></div>` : ''}
  <div class="foot">Generated by FinSight · finsight-vert.vercel.app · ${dark?'Dark':'Light'} Theme · Not financial advice</div>
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
  
  // FIX #2: useNativeDriver set to false for web compatibility
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const t = dark ? DARK : LIGHT;

  useEffect(() => { fetchAnalysis(); }, [id]);

  const fetchAnalysis = async () => {
    setLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const res = await fetch(`${BACKEND}/api/analyses/${id}`, { headers });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setAnalysis(data);
      // useNativeDriver false for web compatibility
      Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: false }).start();
    } catch {
      try {
        const res2 = await fetch(`${BACKEND}/api/public/analyses/${id}`);
        if (res2.ok) {
          const data2 = await res2.json();
          setAnalysis(data2);
          Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: false }).start();
        } else {
          setAnalysis(null);
        }
      } catch {
        setAnalysis(null);
      }
    } finally {
      setLoading(false);
    }
  };

  // FIX #1: Enhanced PDF download with proper error handling and logging
  const handleDownloadPDF = async () => {
    if (!analysis?.result) return;
    setDownloading(true);
    try {
      const company = (analysis.result.company_name || 'FinSight').replace(/[^a-z0-9]/gi, '_');
      const filename = `${company}_Analysis`;
      const html = pdfHTML(analysis.result, dark);

      if (Platform.OS === 'web') {
        // ── Call OUR backend proxy which calls html2pdf.app server-side ──
        // This avoids the 403 CORS error from calling html2pdf.app directly in browser
        console.log('🔄 Calling backend PDF generation endpoint...');
        const response = await fetch(`${BACKEND}/api/generate-pdf`, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/pdf'
          },
          body: JSON.stringify({ html }),
        });

        console.log('📄 PDF Response status:', response.status);

        if (!response.ok) {
          const err = await response.text().catch(() => '');
          console.error('❌ PDF generation error:', err);
          throw new Error(`PDF generation failed (${response.status}): ${err.substring(0, 100)}`);
        }

        const blob = await response.blob();
        console.log('✅ PDF blob size:', blob.size, 'bytes');
        
        // Verify it's actually a PDF
        if (blob.size < 1000) {
          throw new Error('PDF file seems too small, generation may have failed');
        }
        
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${filename}.pdf`;
        document.body.appendChild(a);
        a.click();
        
        // Clean up after a short delay
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 100);
        
        console.log('✅ PDF download initiated');
      } else {
        // ── Mobile: expo-print + expo-sharing ──
        const [PrintModule, SharingModule] = await Promise.all([
          import('expo-print'),
          import('expo-sharing'),
        ]);
        const { uri } = await PrintModule.printToFileAsync({ html, base64: false });
        if (await SharingModule.isAvailableAsync()) {
          await SharingModule.shareAsync(uri, {
            mimeType: 'application/pdf',
            dialogTitle: `Save ${filename}.pdf`,
            UTI: 'com.adobe.pdf',
          });
        }
      }
    } catch (e: any) {
      console.error('❌ PDF download error:', e);
      Alert.alert('Download Failed', e.message || 'Could not generate PDF. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  // FIX #3: Update share URL to use correct domain
  const shareUrl = `https://finsight-vert.vercel.app/share/${id}`;

  const handleCopyLink = async () => {
    if (Platform.OS === 'web' && navigator?.clipboard) {
      await navigator.clipboard.writeText(shareUrl).catch(() => {});
    } else {
      try { await Share.share({ message: shareUrl }); } catch {}
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  const openURL = (url: string) => {
    if (Platform.OS === 'web') { window.open(url, '_blank'); }
    else { Linking.openURL(url).catch(() => {}); }
  };

  const shareMsg = () => {
    const r = analysis?.result;
    if (!r) return '';
    return `📊 ${r.company_name} — Health Score: ${r.health_score}/100 (${r.health_label})\n\n${(r.investor_verdict || '').substring(0, 180)}...\n\nFull analysis: ${shareUrl}`;
  };

  // ✅ WhatsApp Share
const handleWhatsAppShare = () => {
  const r = analysis?.result;
  if (!r) return;
  
  const message = `📊 *${r.company_name}* Financial Analysis

💯 Health Score: *${r.health_score}/100* (${r.health_label})

${r.investor_verdict || r.executive_summary || ''}

📱 View full analysis:
${shareUrl}

_Powered by FinSight_`;

  const url = `https://wa.me/?text=${encodeURIComponent(message)}`;
  
  if (Platform.OS === 'web') {
    window.open(url, '_blank');
  } else {
    Linking.openURL(url).catch(() => Alert.alert('Error', 'Could not open WhatsApp'));
  }
};

// ✅ Twitter Share
const handleTwitterShare = () => {
  const r = analysis?.result;
  if (!r) return;
  
  const tweet = `📊 ${r.company_name} - Financial Health: ${r.health_score}/100 (${r.health_label})

${r.investor_verdict ? r.investor_verdict.substring(0, 100) + '...' : ''}

Full analysis:`;

  const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweet)}&url=${encodeURIComponent(shareUrl)}`;
  
  if (Platform.OS === 'web') {
    window.open(url, '_blank');
  } else {
    Linking.openURL(url).catch(() => Alert.alert('Error', 'Could not open Twitter'));
  }
};

// ✅ Generic Share
const handleGenericShare = async () => {
  const r = analysis?.result;
  if (!r) return;
  
  try {
    await Share.share({
      message: `📊 ${r.company_name} - Health Score: ${r.health_score}/100

${r.investor_verdict || ''}

View analysis: ${shareUrl}`,
      title: `${r.company_name} - Financial Analysis`,
    });
  } catch (error) {
    console.error('Share error:', error);
  }
};

  const handleBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)');
  };

  if (loading) return (
    <View style={[gs.center, { backgroundColor: t.bg }]}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={{ color: t.textSub, marginTop: 14, fontSize: 15 }}>Loading analysis...</Text>
    </View>
  );

  if (!analysis?.result) return (
    <View style={[gs.center, { backgroundColor: t.bg }]}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Text style={{ fontSize: 52, marginBottom: 16 }}>📄</Text>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: '800', marginBottom: 8 }}>Analysis Not Found</Text>
      <Text style={{ color: t.textSub, fontSize: 14, textAlign: 'center', lineHeight: 22, marginBottom: 28, paddingHorizontal: 32 }}>
        This analysis may have been deleted or the link is incorrect.
      </Text>
      <TouchableOpacity style={[gs.btn, { backgroundColor: t.accent }]} onPress={handleBack}>
        <Text style={gs.btnText}>← Go Back</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const sc = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : r.health_score >= 40 ? '#ef4444' : '#dc2626';

  const Card = ({ title, leftBorder, children }: any) => (
    <View style={[gs.card, {
      backgroundColor: t.card,
      borderColor: leftBorder ? 'transparent' : t.border,
      borderLeftColor: leftBorder || t.border,
      borderLeftWidth: leftBorder ? 3 : 1,
    }]}>
      {title ? <Text style={[gs.cardTitle, { color: t.text }]}>{title}</Text> : null}
      {children}
    </View>
  );

  const Row = ({ m }: any) => {
    if (!m?.current || m.current === 'N/A') return null;
    const tc = m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : t.textSub;
    return (
      <View style={[gs.row, { borderBottomColor: t.border }]}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <Text style={[gs.rowLabel, { color: t.text }]}>{m.label}</Text>
          {m.comment && m.comment !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2, fontStyle: 'italic' }}>{m.comment}</Text>}
        </View>
        <View style={{ alignItems: 'flex-end', minWidth: 100 }}>
          <Text style={{ fontSize: 14, fontWeight: '800', color: t.text }}>{m.current}</Text>
          {m.previous && m.previous !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2 }}>vs {m.previous}</Text>}
          {m.change && m.change !== 'N/A' && <Text style={{ fontSize: 12, color: tc, fontWeight: '700', marginTop: 2 }}>{m.trend === 'up' ? '▲' : m.trend === 'down' ? '▼' : ''} {m.change}</Text>}
        </View>
      </View>
    );
  };

  const Stat = ({ label, val, prev, color }: any) => {
    if (!val || val === 'N/A') return null;
    return (
      <View style={[gs.stat, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <Text style={[gs.statVal, { color: color || t.accent }]}>{val}</Text>
        {prev && prev !== 'N/A' && <Text style={{ fontSize: 10, color: t.textSub, marginTop: 2 }}>vs {prev}</Text>}
        <Text style={[gs.statLabel, { color: t.textSub }]}>{label}</Text>
      </View>
    );
  };

  const ScoreBar = ({ c }: any) => {
    const col = c.rating === 'Strong' ? '#22c55e' : c.rating === 'Moderate' ? '#f59e0b' : '#ef4444';
    const pct = c.max > 0 ? (c.score / c.max) * 100 : 0;
    return (
      <View style={[gs.scoreBar, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text style={{ color: t.text, fontSize: 13, fontWeight: '700' }}>{c.category}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <View style={{ backgroundColor: col + '25', borderRadius: 6, paddingHorizontal: 7, paddingVertical: 2 }}>
              <Text style={{ color: col, fontSize: 10, fontWeight: '800' }}>{c.rating}</Text>
            </View>
            <Text style={{ color: col, fontSize: 13, fontWeight: '800' }}>{c.score}/{c.max}</Text>
          </View>
        </View>
        <View style={{ height: 6, backgroundColor: t.border, borderRadius: 3, overflow: 'hidden', marginBottom: 8 }}>
          <View style={{ height: 6, backgroundColor: col, borderRadius: 3, width: `${pct}%` as any }} />
        </View>
        <Text style={{ color: t.textSub, fontSize: 12, lineHeight: 18 }}>{c.reasoning}</Text>
      </View>
    );
  };

  const Dot = ({ text, color }: any) => (
    <View style={gs.dotRow}>
      <View style={[gs.dot, { backgroundColor: color + '25' }]}>
        <Text style={{ color, fontSize: 10, fontWeight: '800' }}>·</Text>
      </View>
      <Text style={{ flex: 1, fontSize: 14, lineHeight: 22, color: t.text }}>{text}</Text>
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Animated.ScrollView style={{ opacity: fadeAnim }} showsVerticalScrollIndicator={false}>

        {/* Top bar */}
        <View style={[gs.topBar, { borderBottomColor: t.border }]}>
          <TouchableOpacity onPress={handleBack}>
            <Text style={[gs.backText, { color: t.accent }]}>← Back</Text>
          </TouchableOpacity>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text style={{ fontSize: 18 }}>📊</Text>
            <Text style={{ color: t.accent, fontSize: 17, fontWeight: '900', letterSpacing: -0.5 }}>FinSight</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text style={{ fontSize: 14 }}>{dark ? '🌙' : '☀️'}</Text>
            <Switch value={dark} onValueChange={setDark}
              trackColor={{ false: '#CBD5E1', true: t.accent }}
              thumbColor="#fff" style={{ transform: [{ scale: 0.8 }] }} />
          </View>
        </View>

        <View style={{ paddingHorizontal: 16 }}>
          {/* Company header */}
          <View style={{ paddingTop: 20, paddingBottom: 16 }}>
            <Text style={{ fontSize: 26, fontWeight: '900', letterSpacing: -0.8, color: t.text, marginBottom: 4 }}>{r.company_name}</Text>
            <Text style={{ fontSize: 13, color: t.textSub }}>{r.statement_type} · {r.period} · {r.currency}</Text>
          </View>

          {/* Score card */}
          <View style={[gs.scoreCard, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '700', letterSpacing: 2, textTransform: 'uppercase', color: t.textSub, marginBottom: 10 }}>FINANCIAL HEALTH SCORE</Text>
            <View style={{ flexDirection: 'row', alignItems: 'flex-end' }}>
              <Text style={{ fontSize: 82, fontWeight: '900', lineHeight: 90, letterSpacing: -4, color: sc }}>{r.health_score}</Text>
              <Text style={{ fontSize: 28, fontWeight: '600', color: t.textSub, marginBottom: 14 }}>/100</Text>
            </View>
            <View style={{ borderRadius: 24, paddingHorizontal: 22, paddingVertical: 7, backgroundColor: sc + '20' }}>
              <Text style={{ fontSize: 16, fontWeight: '800', color: sc }}>{r.health_label}</Text>
            </View>
            {r.health_score_breakdown?.components?.length > 0 && (
              <View style={{ width: '100%', marginTop: 22 }}>
                <Text style={[gs.cardTitle, { color: t.text, marginBottom: 12 }]}>Score Breakdown</Text>
                {r.health_score_breakdown.components.map((c: any, i: number) => <ScoreBar key={i} c={c} />)}
              </View>
            )}
          </View>

          {r.executive_summary && (
            <Card title="📋 Executive Summary">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.executive_summary}</Text>
            </Card>
          )}

          {r.investor_verdict && (
            <Card title="💡 Plain English Verdict" leftBorder={t.accent}>
              <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 16 }}>
                <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.investor_verdict}</Text>
              </View>
            </Card>
          )}

          {r.key_metrics?.filter((m: any) => m.current && m.current !== 'N/A').length > 0 && (
            <Card title="📊 Key Metrics">
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: t.border, marginBottom: 4 }}>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Metric</Text>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Now · Before · Δ</Text>
              </View>
              {r.key_metrics.map((m: any, i: number) => <Row key={i} m={m} />)}
            </Card>
          )}

          {r.profitability?.analysis && (
            <Card title="💰 Profitability">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text, marginBottom: 14 }}>{r.profitability.analysis}</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: r.profitability.key_cost_drivers?.length ? 14 : 0 }}>
                <Stat label="Gross Margin" val={r.profitability.gross_margin_current} prev={r.profitability.gross_margin_previous} />
                <Stat label="EBITDA Margin" val={r.profitability.ebitda_margin_current} prev={r.profitability.ebitda_margin_previous} />
                <Stat label="Net Margin" val={r.profitability.net_margin_current} prev={r.profitability.net_margin_previous} />
                <Stat label="ROE" val={r.profitability.roe} color="#22c55e" />
                <Stat label="ROA" val={r.profitability.roa} color="#22c55e" />
              </View>
              {r.profitability.key_cost_drivers?.length > 0 && (
                <>
                  <Text style={{ fontSize: 12, fontWeight: '700', color: t.text, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>Cost Drivers</Text>
                  {r.profitability.key_cost_drivers.map((d: string, i: number) => (
                    <Text key={i} style={{ fontSize: 13, lineHeight: 22, color: t.textSub, marginBottom: 4 }}>· {d}</Text>
                  ))}
                </>
              )}
            </Card>
          )}

          {r.growth?.analysis && (
            <Card title="📈 Growth">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text, marginBottom: 14 }}>{r.growth.analysis}</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: r.growth.guidance && r.growth.guidance !== 'N/A' ? 14 : 0 }}>
                <Stat label="Revenue Growth" val={r.growth.revenue_growth_yoy} color="#22c55e" />
                <Stat label="Profit Growth" val={r.growth.profit_growth_yoy} color="#22c55e" />
              </View>
              {r.growth.guidance && r.growth.guidance !== 'N/A' && (
                <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 14 }}>
                  <Text style={{ fontSize: 12, fontWeight: '700', color: t.accent, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>📌 Management Guidance</Text>
                  <Text style={{ fontSize: 13, lineHeight: 20, color: t.text }}>{r.growth.guidance}</Text>
                </View>
              )}
            </Card>
          )}

          {r.liquidity?.analysis && (
            <Card title="💧 Liquidity & Cash">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text, marginBottom: 14 }}>{r.liquidity.analysis}</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                <Stat label="Current Ratio" val={r.liquidity.current_ratio} />
                <Stat label="Cash" val={r.liquidity.cash_position} />
                <Stat label="Operating CF" val={r.liquidity.operating_cash_flow} />
                <Stat label="Free CF" val={r.liquidity.free_cash_flow} />
              </View>
            </Card>
          )}

          {r.debt?.analysis && (
            <Card title="🏦 Debt & Leverage">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text, marginBottom: 14 }}>{r.debt.analysis}</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: r.debt.debt_trend ? 12 : 0 }}>
                <Stat label="Total Debt" val={r.debt.total_debt} />
                <Stat label="D/E" val={r.debt.debt_to_equity} />
                <Stat label="Interest Coverage" val={r.debt.interest_coverage} />
              </View>
              {r.debt.debt_trend && (
                <View style={{ backgroundColor: r.debt.debt_trend === 'Decreasing' ? '#22c55e15' : r.debt.debt_trend === 'Increasing' ? '#ef444415' : t.cardAlt, borderRadius: 10, padding: 10, alignSelf: 'flex-start' }}>
                  <Text style={{ color: r.debt.debt_trend === 'Decreasing' ? '#22c55e' : r.debt.debt_trend === 'Increasing' ? '#ef4444' : t.textSub, fontWeight: '700', fontSize: 13 }}>Trend: {r.debt.debt_trend}</Text>
                </View>
              )}
            </Card>
          )}

          {r.management_commentary && (
            <Card title="🎙️ Management Commentary">
              {r.management_commentary.overall_tone && (
                <View style={{ backgroundColor: r.management_commentary.overall_tone === 'Positive' ? '#22c55e15' : r.management_commentary.overall_tone === 'Concerned' ? '#ef444415' : '#f59e0b15', borderRadius: 10, padding: 10, marginBottom: 14, alignSelf: 'flex-start' }}>
                  <Text style={{ color: r.management_commentary.overall_tone === 'Positive' ? '#22c55e' : r.management_commentary.overall_tone === 'Concerned' ? '#ef4444' : '#f59e0b', fontWeight: '700', fontSize: 13 }}>Tone: {r.management_commentary.overall_tone}</Text>
                </View>
              )}
              {r.management_commentary.key_points?.map((p: string, i: number) => (
                <Text key={i} style={{ fontSize: 13, lineHeight: 22, color: t.text, marginBottom: 6 }}>· {p}</Text>
              ))}
              {r.management_commentary.outlook_statement && r.management_commentary.outlook_statement !== 'N/A' && (
                <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 14, marginTop: 12 }}>
                  <Text style={{ fontSize: 12, fontWeight: '700', color: t.accent, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>Outlook</Text>
                  <Text style={{ fontSize: 13, lineHeight: 20, color: t.text }}>{r.management_commentary.outlook_statement}</Text>
                </View>
              )}
            </Card>
          )}

          {r.segments?.filter((seg: any) => seg.name).length > 0 && (
            <Card title="🏢 Segments">
              {r.segments.filter((seg: any) => seg.name).map((seg: any, i: number) => (
                <View key={i} style={[gs.segCard, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
                  <Text style={{ color: t.text, fontSize: 14, fontWeight: '700', marginBottom: 8 }}>{seg.name}</Text>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                    {seg.revenue && <View style={{ backgroundColor: t.accentBg, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: t.accent, fontSize: 11, fontWeight: '700' }}>Rev: {seg.revenue}</Text></View>}
                    {seg.growth && <View style={{ backgroundColor: '#22c55e20', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: '#22c55e', fontSize: 11, fontWeight: '700' }}>↑ {seg.growth}</Text></View>}
                    {seg.margin && <View style={{ backgroundColor: '#f59e0b20', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: '#f59e0b', fontSize: 11, fontWeight: '700' }}>Margin: {seg.margin}</Text></View>}
                  </View>
                  {seg.comment && <Text style={{ fontSize: 12, color: t.textSub }}>{seg.comment}</Text>}
                </View>
              ))}
            </Card>
          )}

          {r.highlights?.length > 0 && (
            <Card title="✅ Key Strengths">
              {r.highlights.map((h: string, i: number) => <Dot key={i} text={h} color="#22c55e" />)}
            </Card>
          )}

          {r.risks?.length > 0 && (
            <Card title="⚠️ Key Risks">
              {r.risks.map((risk: string, i: number) => <Dot key={i} text={risk} color="#ef4444" />)}
            </Card>
          )}

          {r.what_to_watch?.length > 0 && (
            <Card title="🔭 What to Watch">
              {r.what_to_watch.map((w: string, i: number) => <Dot key={i} text={w} color={t.accent} />)}
            </Card>
          )}

          {/* Save & Share Panel */}
          <View style={[gs.sharePanel, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', color: t.textSub, textAlign: 'center', marginBottom: 18 }}>SAVE & SHARE</Text>

            <TouchableOpacity
              style={[gs.pdfBtn, { backgroundColor: t.accent, opacity: downloading ? 0.7 : 1 }]}
              onPress={handleDownloadPDF}
              disabled={downloading}
            >
              {downloading
                ? <ActivityIndicator color="#fff" />
                : <>
                    <Text style={{ fontSize: 22 }}>⬇️</Text>
                    <View>
                      <Text style={{ color: '#fff', fontSize: 16, fontWeight: '800' }}>Download PDF Report</Text>
                      <Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, marginTop: 2 }}>Saves in {dark ? 'dark' : 'light'} theme</Text>
                    </View>
                  </>
              }
            </TouchableOpacity>

            <View style={{ flexDirection: 'row', gap: 10, marginBottom: 12 }}>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleWhatsAppShare}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>💬</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>WhatsApp</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: '#000' }]} onPress={handleTwitterShare}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>𝕏</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Twitter</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: '#0052FF' }]} onPress={handleGenericShare}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>📤</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Share</Text>
              </TouchableOpacity>
            </View>

            <TouchableOpacity
              style={[gs.copyBtn, { borderColor: copied ? '#22c55e' : t.accent, backgroundColor: copied ? '#22c55e15' : t.accentBg }]}
              onPress={handleCopyLink}
            >
              <Text style={{ color: copied ? '#22c55e' : t.accent, fontSize: 15, fontWeight: '700' }}>
                {copied ? '✅ Link Copied!' : '🔗 Copy Shareable Link'}
              </Text>
              {!copied && <Text style={{ color: t.textSub, fontSize: 11, marginTop: 4, textAlign: 'center' }}>Anyone can open this — no login needed</Text>}
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={[gs.backBtn, { borderColor: t.border }]} onPress={handleBack}>
            <Text style={{ color: t.textSub, fontSize: 14, fontWeight: '600' }}>← Back</Text>
          </TouchableOpacity>
          <View style={{ height: 60 }} />
        </View>
      </Animated.ScrollView>
    </View>
  );
}

const gs = StyleSheet.create({
  center:     { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  btn:        { borderRadius: 14, padding: 16, paddingHorizontal: 32 },
  btnText:    { color: '#fff', fontSize: 15, fontWeight: '700' },
  topBar:     { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 56, paddingBottom: 16, borderBottomWidth: 1 },
  backText:   { fontSize: 15, fontWeight: '600' },
  card:       { borderRadius: 20, padding: 18, marginBottom: 14, borderWidth: 1, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 10, elevation: 3 },
  cardTitle:  { fontSize: 15, fontWeight: '800', marginBottom: 14, letterSpacing: -0.3 },
  scoreCard:  { borderRadius: 22, padding: 24, alignItems: 'center', marginBottom: 14, borderWidth: 1 },
  scoreBar:   { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  row:        { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 11, borderBottomWidth: 1 },
  rowLabel:   { fontSize: 13, fontWeight: '600' },
  stat:       { borderRadius: 14, padding: 14, minWidth: '30%', flex: 1, alignItems: 'center', borderWidth: 1 },
  statVal:    { fontSize: 16, fontWeight: '800', letterSpacing: -0.5 },
  statLabel:  { fontSize: 10, marginTop: 5, textAlign: 'center', fontWeight: '600' },
  dotRow:     { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 12 },
  dot:        { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1, flexShrink: 0 },
  segCard:    { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  sharePanel: { borderRadius: 22, padding: 20, marginBottom: 14, borderWidth: 1 },
  pdfBtn:     { borderRadius: 16, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 14 },
  shareBtn:   { flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  copyBtn:    { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1.5 },
  backBtn:    { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1, marginBottom: 4 },
});
