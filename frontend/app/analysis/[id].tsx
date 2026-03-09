import React, { useEffect, useState, useRef } from 'react';
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
  TouchableOpacity, Switch, Share, Platform, Alert, Linking, Animated, StatusBar
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const DARK  = { bg:'#060B18', card:'#0D1426', cardAlt:'#111B35', text:'#F0F4FF', sub:'#6B82A8', border:'#1E2D4A', accent:'#4F8AFF', accentBg:'#0D1D3A' };
const LIGHT = { bg:'#F4F7FF', card:'#FFFFFF',  cardAlt:'#F0F4FF', text:'#0A0E1A', sub:'#6B7280',  border:'#E5E7EB', accent:'#0052FF', accentBg:'#EEF4FF' };

// ─── Safe helpers ─────────────────────────────────────────────────────────────
const safe = (v: any): string | null =>
  v && v !== 'N/A' && v !== '' && v !== 'Not reported' && v !== 'null' &&
  !String(v).toLowerCase().startsWith('not available')
    ? String(v) : null;

// ─── Color helpers ────────────────────────────────────────────────────────────
const scoreColor  = (s: number) => s >= 80 ? '#22c55e' : s >= 60 ? '#3b82f6' : s >= 40 ? '#f59e0b' : '#ef4444';
const ratingColor = (r: string) => r === 'Strong' ? '#22c55e' : r === 'Average' ? '#f59e0b' : '#ef4444';
const trendColor  = (t: string, accent: string) => t === 'up' ? '#22c55e' : t === 'down' ? '#ef4444' : accent;
const signalColor = (s: string) => s === 'Bullish' ? '#22c55e' : s === 'Bearish' ? '#ef4444' : '#94a3b8';
const labelColor  = (l: string) => ({ 'Strong Buy':'#22c55e', Buy:'#4ade80', Hold:'#f59e0b', Reduce:'#ef4444', Avoid:'#dc2626' }[l] || '#4F8AFF');
const debtColor   = (l: string) => l === 'Comfortable' ? '#22c55e' : l === 'Elevated' ? '#f59e0b' : '#ef4444';

// ─── FIX: cfqColor only operates on short label words, not long sentences ────
const cfqLabel = (q: string): string => {
  if (!q) return '';
  const ql = q.toLowerCase();
  if (ql.startsWith('strong')) return 'Strong';
  if (ql.startsWith('moderate')) return 'Moderate';
  if (ql.startsWith('weak')) return 'Weak';
  // backend now sends cash_conversion_quality_label — use that if available
  return '';
};
const cfqColor = (q: string): string => {
  const label = cfqLabel(q);
  return label === 'Strong' ? '#22c55e' : label === 'Moderate' ? '#f59e0b' : label === 'Weak' ? '#ef4444' : '#6B82A8';
};

// ─── PDF builder ─────────────────────────────────────────────────────────────
function buildPDF(r: any, dark: boolean): string {
  const bg = dark ? '#060B18' : '#ffffff';
  const cardBg = dark ? '#0D1426' : '#f8faff';
  const textC = dark ? '#F0F4FF' : '#0A0E1A';
  const subC = dark ? '#6B82A8' : '#6b7280';
  const borderC = dark ? '#1E2D4A' : '#e5e7eb';
  const accentC = dark ? '#4F8AFF' : '#0052FF';
  const sc = scoreColor(r.health_score || 0);
  const ic = labelColor(r.investment_label || '');

  const sec = (title: string, body: string) =>
    `<div style="margin-bottom:28px;page-break-inside:avoid">
      <div style="font-size:11px;font-weight:800;color:${textC};border-bottom:2px solid ${borderC};padding-bottom:6px;margin-bottom:12px;text-transform:uppercase;letter-spacing:1.2px">${title}</div>
      ${body}
    </div>`;

  const pill = (t: string, c: string) =>
    `<span style="display:inline-block;background:${c}22;color:${c};font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;margin:2px 4px 2px 0">${t}</span>`;

  // FIX: box() now skips "Not available" values so they don't render as red boxes
  const box = (label: string, val: string | null | undefined, col = accentC) => {
    if (!val) return '';
    const v = String(val);
    if (v.toLowerCase().startsWith('not available') || v === 'N/A' || v === '') return '';
    return `<div style="display:inline-block;background:${cardBg};border:1px solid ${borderC};border-radius:10px;padding:12px 16px;margin:4px;text-align:center;min-width:90px">
      <div style="font-size:17px;font-weight:900;color:${col}">${v}</div>
      <div style="font-size:10px;color:${subC};margin-top:4px;font-weight:600">${label}</div>
    </div>`;
  };

  const li = (arr: any[], col = textC) =>
    (arr || []).filter(Boolean).map(x =>
      `<li style="margin-bottom:7px;font-size:13px;color:${col};line-height:1.75">${typeof x === 'string' ? x : (x.question ? `<strong>${x.question}</strong><br/>${x.answer}` : JSON.stringify(x))}</li>`
    ).join('');

  const scoreRows = (r.health_score_breakdown?.components || []).map((c: any) => {
    const col = ratingColor(c.rating);
    const pct = c.max > 0 ? Math.round((c.score / c.max) * 100) : 0;
    return `<tr>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-weight:700;font-size:13px;color:${textC};width:25%">${c.category}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};width:35%">
        <div style="background:${borderC};border-radius:4px;height:6px"><div style="background:${col};height:6px;border-radius:4px;width:${pct}%"></div></div>
      </td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-weight:800;font-size:13px;color:${col};text-align:center">${c.score}/${c.max}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-size:11px;font-weight:700;color:${col};text-align:center">${c.rating}</td>
    </tr>
    <tr><td colspan="4" style="padding:4px 12px 10px;border-bottom:1px solid ${borderC};font-size:11px;color:${subC};line-height:1.65">${c.reasoning}</td></tr>`;
  }).join('');

  const metricRows = (r.key_metrics || []).filter((m: any) => safe(m.current)).map((m: any) =>
    `<tr>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-weight:700;font-size:13px;color:${textC}">${m.label}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-weight:800;font-size:13px;color:${textC};text-align:right">${m.current}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-size:12px;color:${subC};text-align:right">${m.previous || '—'}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};font-size:12px;font-weight:700;color:${m.trend === 'up' ? '#22c55e' : m.trend === 'down' ? '#ef4444' : subC};text-align:right">${m.change || '—'}</td>
      <td style="padding:9px 12px;border-bottom:1px solid ${borderC};text-align:right"><span style="background:${signalColor(m.signal)}22;color:${signalColor(m.signal)};font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px">${m.signal || '—'}</span></td>
    </tr>
    ${m.comment ? `<tr><td colspan="5" style="padding:2px 12px 8px;border-bottom:1px solid ${borderC};font-size:11px;color:${subC};font-style:italic">${m.comment}</td></tr>` : ''}`
  ).join('');

  const cfd = r.cash_flow_deep_dive || {};
  const bsd = r.balance_sheet_deep_dive || {};
  const gq = r.growth_quality || {};
  const indc = r.industry_context || {};
  const pa = r.profitability || {};
  const lq = r.liquidity || {};
  // Use the short label for color rendering
  const cfQualityLabel = cfd.cash_conversion_quality_label || cfqLabel(cfd.cash_conversion_quality || '');

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,'Segoe UI',Helvetica,sans-serif;background:${bg};color:${textC};-webkit-print-color-adjust:exact;print-color-adjust:exact}.wrap{max-width:860px;margin:0 auto;padding:44px 40px}ul{padding-left:18px;margin:6px 0}table{width:100%;border-collapse:collapse}@page{margin:0.6in}</style>
</head><body><div class="wrap">

<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:36px;padding-bottom:20px;border-bottom:3px solid ${accentC}">
  <div><div style="font-size:20px;font-weight:900;color:${accentC}">📊 FinSight</div><div style="font-size:11px;color:${subC};margin-top:3px">Institutional Equity Research</div></div>
  <div style="text-align:right">
    <div style="font-size:22px;font-weight:900;color:${textC}">${r.company_name || 'Analysis'}</div>
    <div style="font-size:12px;color:${subC};margin-top:4px">${[r.statement_type, r.period, r.currency].filter(Boolean).join(' · ')}</div>
    <div style="font-size:11px;color:${subC};margin-top:3px">Generated ${new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })}</div>
  </div>
</div>

${r.headline ? `<div style="font-size:15px;font-weight:700;background:${cardBg};border-left:4px solid ${accentC};padding:14px 18px;border-radius:0 12px 12px 0;margin-bottom:24px;line-height:1.55;color:${textC}">${r.headline}</div>` : ''}

<div style="display:flex;gap:16px;margin-bottom:28px;flex-wrap:wrap">
  <div style="flex:1;min-width:200px;text-align:center;background:${cardBg};border-radius:16px;padding:28px;border:1px solid ${borderC}">
    <div style="font-size:10px;color:${subC};text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">Health Score</div>
    <div style="font-size:72px;font-weight:900;color:${sc};line-height:1;letter-spacing:-3px">${r.health_score}<span style="font-size:24px;color:${subC}">/100</span></div>
    ${pill(r.health_label || '', sc)}
  </div>
  <div style="flex:1;min-width:200px;text-align:center;background:${cardBg};border-radius:16px;padding:28px;border:1px solid ${borderC}">
    <div style="font-size:10px;color:${subC};text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">Investment Rating</div>
    <div style="font-size:34px;font-weight:900;color:${ic};margin-bottom:12px">${r.investment_label || '—'}</div>
    <div style="font-size:12px;color:${textC};line-height:1.65">${(r.investor_verdict || '').substring(0, 140)}${(r.investor_verdict || '').length > 140 ? '…' : ''}</div>
  </div>
</div>

${scoreRows ? sec('📐 Score Breakdown', `<table><tbody>${scoreRows}</tbody></table>`) : ''}
${r.executive_summary ? sec('📋 Executive Summary', `<p style="font-size:13px;line-height:1.9;color:${textC}">${r.executive_summary}</p>`) : ''}

${r.for_long_term_investors || r.for_short_term_traders ? sec('👥 Investor Perspectives', `
  ${r.for_long_term_investors ? `<div style="margin-bottom:14px"><div style="font-size:10px;font-weight:800;color:#22c55e;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">🏛 Long-Term Investors</div><p style="font-size:13px;line-height:1.8;color:${textC}">${r.for_long_term_investors}</p></div>` : ''}
  ${r.for_short_term_traders ? `<div><div style="font-size:10px;font-weight:800;color:#f59e0b;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">⚡ Short-Term Traders</div><p style="font-size:13px;line-height:1.8;color:${textC}">${r.for_short_term_traders}</p></div>` : ''}
`) : ''}

${r.bottom_line ? sec('💡 Bottom Line', `<div style="background:${cardBg};border-left:4px solid ${accentC};padding:15px 18px;border-radius:0 12px 12px 0;font-size:15px;font-weight:700;line-height:1.6;color:${textC}">${r.bottom_line}</div>`) : ''}

${metricRows ? sec('📊 Key Metrics', `<table><thead><tr>
  <th style="padding:8px 12px;font-size:10px;color:${subC};text-align:left;text-transform:uppercase;border-bottom:2px solid ${borderC}">Metric</th>
  <th style="padding:8px 12px;font-size:10px;color:${subC};text-align:right;text-transform:uppercase;border-bottom:2px solid ${borderC}">Current</th>
  <th style="padding:8px 12px;font-size:10px;color:${subC};text-align:right;text-transform:uppercase;border-bottom:2px solid ${borderC}">Previous</th>
  <th style="padding:8px 12px;font-size:10px;color:${subC};text-align:right;text-transform:uppercase;border-bottom:2px solid ${borderC}">Change</th>
  <th style="padding:8px 12px;font-size:10px;color:${subC};text-align:right;text-transform:uppercase;border-bottom:2px solid ${borderC}">Signal</th>
</tr></thead><tbody>${metricRows}</tbody></table>`) : ''}

${pa.analysis ? sec('💹 Profitability', `
  <div style="display:flex;flex-wrap:wrap;margin-bottom:14px">
    ${box('Net Margin', pa.net_margin_current, '#22c55e')}
    ${box('EBITDA Margin', pa.ebitda_margin_current, '#4F8AFF')}
    ${box('ROE', pa.roe, '#22c55e')}
    ${box('ROA', pa.roa, '#f59e0b')}
  </div>
  <p style="font-size:13px;line-height:1.85;color:${textC}">${pa.analysis}</p>
`) : ''}

${lq.analysis ? sec('💧 Liquidity', `
  <div style="display:flex;flex-wrap:wrap;margin-bottom:14px">
    ${box('Current Ratio', lq.current_ratio, '#4F8AFF')}
    ${box('Quick Ratio', lq.quick_ratio, '#4F8AFF')}
    ${box('Cash Position', lq.cash_position)}
    ${box('Free Cash Flow', lq.free_cash_flow, '#22c55e')}
  </div>
  <p style="font-size:13px;line-height:1.85;color:${textC}">${lq.analysis}</p>
`) : ''}

${cfd.ocf_vs_pat_insight ? sec('🌊 Cash Flow Quality', `
  <div style="display:flex;flex-wrap:wrap;margin-bottom:14px">
    ${box('Operating CF', cfd.operating_cf)}
    ${box('Free CF', cfd.free_cash_flow, '#22c55e')}
    ${box('Capex', cfd.capex)}
    ${cfQualityLabel ? box('Quality', cfQualityLabel, cfqColor(cfQualityLabel)) : ''}
  </div>
  <p style="font-size:13px;line-height:1.85;color:${textC}">${cfd.ocf_vs_pat_insight}</p>
`) : ''}

${bsd.debt_to_equity ? sec('🏗️ Balance Sheet Health', `
  <div style="display:flex;flex-wrap:wrap;margin-bottom:14px">
    ${box('D/E Ratio', bsd.debt_to_equity, '#f59e0b')}
    ${box('Interest Cover', bsd.interest_coverage, '#22c55e')}
    ${box('Total Debt', bsd.total_debt)}
    ${box('Net Worth', bsd.net_worth)}
    ${bsd.debt_comfort_level ? box('Comfort Level', bsd.debt_comfort_level, debtColor(bsd.debt_comfort_level)) : ''}
  </div>
  ${bsd.asset_quality ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:8px">${bsd.asset_quality}</p>` : ''}
  ${bsd.debt_profile ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:8px">${bsd.debt_profile}</p>` : ''}
  ${bsd.working_capital_insight ? `<p style="font-size:13px;line-height:1.85;color:${textC}">${bsd.working_capital_insight}</p>` : ''}
`) : ''}

${gq.revenue_growth_context ? sec('📈 Growth Quality', `
  ${gq.revenue_growth_context ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:8px"><strong style="color:${subC}">Revenue: </strong>${gq.revenue_growth_context}</p>` : ''}
  ${gq.profit_growth_context ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:8px"><strong style="color:${subC}">Profit: </strong>${gq.profit_growth_context}</p>` : ''}
  ${gq.margin_trend ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:8px"><strong style="color:${subC}">Margins: </strong>${gq.margin_trend}</p>` : ''}
  ${gq.growth_outlook ? `<p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:12px"><strong style="color:${subC}">Outlook: </strong>${gq.growth_outlook}</p>` : ''}
  <div style="display:flex;gap:20px;flex-wrap:wrap">
    ${gq.catalysts?.length ? `<div style="flex:1;min-width:180px"><div style="font-size:10px;font-weight:800;color:#22c55e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Catalysts</div><ul>${li(gq.catalysts, '#22c55e')}</ul></div>` : ''}
    ${gq.headwinds?.length ? `<div style="flex:1;min-width:180px"><div style="font-size:10px;font-weight:800;color:#ef4444;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Headwinds</div><ul>${li(gq.headwinds, '#ef4444')}</ul></div>` : ''}
  </div>
`) : ''}

${indc.competitive_position ? sec('🏭 Industry Context', `
  <p style="font-size:13px;line-height:1.85;color:${textC};margin-bottom:12px">${indc.competitive_position}</p>
  <div style="display:flex;gap:20px;flex-wrap:wrap">
    ${indc.sector_tailwinds?.length ? `<div style="flex:1;min-width:180px"><div style="font-size:10px;font-weight:800;color:#22c55e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Tailwinds</div><ul>${li(indc.sector_tailwinds)}</ul></div>` : ''}
    ${indc.sector_headwinds?.length ? `<div style="flex:1;min-width:180px"><div style="font-size:10px;font-weight:800;color:#ef4444;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Headwinds</div><ul>${li(indc.sector_headwinds)}</ul></div>` : ''}
  </div>
  ${indc.peer_benchmarks ? `<p style="font-size:12px;color:${subC};margin-top:10px;line-height:1.7">${indc.peer_benchmarks}</p>` : ''}
  ${indc.regulatory_environment ? `<p style="font-size:12px;color:${subC};margin-top:6px;line-height:1.7">${indc.regulatory_environment}</p>` : ''}
`) : ''}

${r.strengths_and_moats?.length ? sec('✅ Strengths & Moats', `<ul>${li(r.strengths_and_moats, '#22c55e')}</ul>`) : ''}
${r.red_flags?.length ? sec('🚩 Red Flags', `<ul>${li(r.red_flags, '#ef4444')}</ul>`) : ''}
${r.risks?.length ? sec('⚠️ Key Risks', `<ul>${li(r.risks)}</ul>`) : ''}
${r.highlights?.length ? sec('🌟 Highlights', `<ul>${li(r.highlights, '#22c55e')}</ul>`) : ''}
${r.key_monitorables?.length ? sec('🔭 Key Monitorables', `<ul>${li(r.key_monitorables, accentC)}</ul>`) : ''}
${r.what_to_watch?.length ? sec('👁️ What to Watch', `<ul>${li(r.what_to_watch)}</ul>`) : ''}

${r.investor_faq?.length ? sec('❓ Investor FAQ', r.investor_faq.map((f: any) =>
  `<div style="margin-bottom:14px"><div style="font-size:13px;font-weight:700;color:${textC};margin-bottom:4px">${f.question || f}</div>${f.answer ? `<div style="font-size:13px;color:${subC};line-height:1.75">${f.answer}</div>` : ''}</div>`
).join('')) : ''}

${r.investor_verdict ? sec('🎯 Final Verdict', `<div style="background:${cardBg};border-left:4px solid ${accentC};padding:16px 20px;border-radius:0 12px 12px 0;font-size:14px;line-height:1.9;color:${textC}">${r.investor_verdict}</div>`) : ''}

<div style="text-align:center;color:${subC};font-size:11px;margin-top:48px;padding-top:18px;border-top:1px solid ${borderC}">
  Generated by FinSight · finsight-vert.vercel.app · ${dark ? 'Dark' : 'Light'} Theme · For informational purposes only — not financial advice
</div>
</div></body></html>`;
}

// ─── Main Screen ──────────────────────────────────────────────────────────────
export default function AnalysisScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);
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
      Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: false }).start();
    } catch {
      try {
        const r2 = await fetch(`${BACKEND}/api/public/analyses/${id}`);
        if (r2.ok) {
          setAnalysis(await r2.json());
          Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: false }).start();
        } else setAnalysis(null);
      } catch { setAnalysis(null); }
    } finally { setLoading(false); }
  };

  // ─── FIX: PDF download with proper error handling ─────────────────────────
  const handleDownloadPDF = async () => {
    if (!analysis?.result) return;
    setDownloading(true);
    try {
      const company = (analysis.result.company_name || 'FinSight').replace(/[^a-z0-9]/gi, '_');
      const html = buildPDF(analysis.result, dark);

      if (Platform.OS === 'web') {
        // Try backend PDF generation first
        try {
          const resp = await fetch(`${BACKEND}/api/generate-pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/pdf' },
            body: JSON.stringify({ html }),
          });
          if (resp.ok) {
            const blob = await resp.blob();
            if (blob.size > 1000) {
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${company}_FinSight_Analysis.pdf`;
              document.body.appendChild(a);
              a.click();
              setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
              return;
            }
          }
        } catch { /* fall through to print */ }

        // Fallback: open print dialog
        const win = window.open('', '_blank');
        if (win) {
          win.document.write(html);
          win.document.close();
          win.onload = () => { win.focus(); win.print(); };
        } else {
          Alert.alert('PDF', 'Please allow popups to download the PDF, or use the print shortcut (Ctrl+P / Cmd+P).');
        }
      } else {
        const [P, S] = await Promise.all([import('expo-print'), import('expo-sharing')]);
        const { uri } = await P.printToFileAsync({ html, base64: false });
        if (await S.isAvailableAsync()) {
          await S.shareAsync(uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf' });
        } else {
          Alert.alert('Saved', 'PDF saved to your device.');
        }
      }
    } catch (e: any) {
      Alert.alert('Download Failed', e.message || 'Could not generate PDF. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

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

  const handleWhatsApp = () => {
    const r = analysis?.result;
    if (!r) return;
    const msg = `📊 *${r.company_name}* Financial Analysis\n\n💯 Health Score: *${r.health_score}/100* (${r.health_label})\n🎯 Rating: *${r.investment_label || 'N/A'}*\n\n${(r.bottom_line || r.investor_verdict || '').substring(0, 200)}\n\n📱 Full analysis:\n${shareUrl}\n\n_Powered by FinSight_`;
    const url = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    Platform.OS === 'web' ? window.open(url, '_blank') : Linking.openURL(url).catch(() => {});
  };

  const handleTwitter = () => {
    const r = analysis?.result;
    if (!r) return;
    const tweet = `📊 ${r.company_name} — ${r.health_score}/100 (${r.health_label}) · ${r.investment_label || ''}\n\n${(r.bottom_line || '').substring(0, 120)}\n\nFull analysis:`;
    const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweet)}&url=${encodeURIComponent(shareUrl)}`;
    Platform.OS === 'web' ? window.open(url, '_blank') : Linking.openURL(url).catch(() => {});
  };

  const handleShare = async () => {
    const r = analysis?.result;
    if (!r) return;
    try {
      await Share.share({
        message: `📊 ${r.company_name} — ${r.health_score}/100 · ${r.investment_label || ''}\n${r.bottom_line || ''}\n\n${shareUrl}`,
        title: `${r.company_name} Analysis`,
      });
    } catch {}
  };

  const handleBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)');
  };

  if (loading) return (
    <View style={[s.center, { backgroundColor: t.bg }]}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ActivityIndicator size="large" color={t.accent} />
      <Text style={{ color: t.sub, marginTop: 14, fontSize: 15 }}>Loading analysis…</Text>
    </View>
  );

  if (!analysis?.result) return (
    <View style={[s.center, { backgroundColor: t.bg }]}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Text style={{ fontSize: 54, marginBottom: 16 }}>📄</Text>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: '800', marginBottom: 8 }}>Analysis Not Found</Text>
      <Text style={{ color: t.sub, fontSize: 14, textAlign: 'center', lineHeight: 22, marginBottom: 28, paddingHorizontal: 32 }}>
        This analysis may have been deleted or the link is incorrect.
      </Text>
      <TouchableOpacity style={[s.btn, { backgroundColor: t.accent }]} onPress={handleBack}>
        <Text style={s.btnTxt}>← Go Back</Text>
      </TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const sc = scoreColor(r.health_score || 0);
  const ic = labelColor(r.investment_label || '');

  const Card = ({ title, leftBorder, children }: any) => (
    <View style={[s.card, {
      backgroundColor: t.card, borderColor: t.border,
      borderLeftColor: leftBorder || t.border,
      borderLeftWidth: leftBorder ? 3 : 1,
    }]}>
      {title && <Text style={[s.cardTitle, { color: t.text }]}>{title}</Text>}
      {children}
    </View>
  );

  const Stat = ({ label, value, color }: any) => {
    if (!safe(value)) return null;
    return (
      <View style={[s.stat, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <Text style={{ fontSize: 16, fontWeight: '800', color: color || t.accent }}>{value}</Text>
        <Text style={{ fontSize: 10, color: t.sub, marginTop: 4, textAlign: 'center', fontWeight: '600' }}>{label}</Text>
      </View>
    );
  };

  const Dot = ({ text, color }: any) => (
    <View style={s.dotRow}>
      <View style={[s.dotCircle, { backgroundColor: (color || t.accent) + '22' }]}>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color || t.accent }} />
      </View>
      <Text style={{ flex: 1, fontSize: 14, lineHeight: 22, color: t.text }}>{String(text)}</Text>
    </View>
  );

  const ScoreBar = ({ c }: any) => {
    if (!c) return null;
    const col = ratingColor(c.rating);
    const pct = c.max > 0 ? (c.score / c.max) * 100 : 0;
    return (
      <View style={[s.scoreBarBox, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <Text style={{ color: t.text, fontSize: 13, fontWeight: '700' }}>{c.category}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <View style={{ backgroundColor: col + '22', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 }}>
              <Text style={{ color: col, fontSize: 10, fontWeight: '800' }}>{c.rating}</Text>
            </View>
            <Text style={{ color: col, fontSize: 13, fontWeight: '800' }}>{c.score}/{c.max}</Text>
          </View>
        </View>
        <View style={{ height: 5, backgroundColor: t.border, borderRadius: 3, overflow: 'hidden', marginBottom: 8 }}>
          <View style={{ height: 5, backgroundColor: col, borderRadius: 3, width: `${pct}%` as any }} />
        </View>
        <Text style={{ color: t.sub, fontSize: 12, lineHeight: 18 }}>{c.reasoning}</Text>
      </View>
    );
  };

  const MetricRow = ({ m }: any) => {
    if (!safe(m?.current)) return null;
    const tc = trendColor(m.trend || '', t.accent);
    const sc2 = signalColor(m.signal || '');
    return (
      <View style={[s.row, { borderBottomColor: t.border }]}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <Text style={{ fontSize: 13, fontWeight: '600', color: t.text }}>{m.label}</Text>
          {safe(m.comment) && <Text style={{ fontSize: 11, color: t.sub, marginTop: 2, fontStyle: 'italic', lineHeight: 17 }}>{m.comment}</Text>}
        </View>
        <View style={{ alignItems: 'flex-end', minWidth: 130 }}>
          <Text style={{ fontSize: 14, fontWeight: '800', color: t.text }}>{m.current}</Text>
          {safe(m.previous) && <Text style={{ fontSize: 11, color: t.sub, marginTop: 1 }}>vs {m.previous}</Text>}
          <View style={{ flexDirection: 'row', gap: 6, marginTop: 3 }}>
            {safe(m.change) && (
              <Text style={{ fontSize: 11, fontWeight: '700', color: tc }}>
                {m.trend === 'up' ? '▲' : m.trend === 'down' ? '▼' : ''} {m.change}
              </Text>
            )}
            {safe(m.signal) && (
              <View style={{ backgroundColor: sc2 + '22', borderRadius: 5, paddingHorizontal: 6, paddingVertical: 1 }}>
                <Text style={{ fontSize: 9, fontWeight: '800', color: sc2 }}>{m.signal}</Text>
              </View>
            )}
          </View>
        </View>
      </View>
    );
  };

  const pa = r.profitability || {};
  const lq = r.liquidity || {};
  const cfd = r.cash_flow_deep_dive || {};
  const bsd = r.balance_sheet_deep_dive || {};
  const gq = r.growth_quality || {};
  const indc = r.industry_context || {};
  const faq = r.investor_faq || [];
  // Use short label for color logic
  const cfQualityLabel = cfd.cash_conversion_quality_label || cfqLabel(cfd.cash_conversion_quality || '');

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Animated.ScrollView style={{ opacity: fadeAnim }} showsVerticalScrollIndicator={false}>

        <View style={[s.topBar, { borderBottomColor: t.border }]}>
          <TouchableOpacity onPress={handleBack}>
            <Text style={{ color: t.accent, fontSize: 15, fontWeight: '600' }}>← Back</Text>
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

          <View style={{ paddingTop: 20, paddingBottom: 14 }}>
            <Text style={{ fontSize: 26, fontWeight: '900', letterSpacing: -0.8, color: t.text, marginBottom: 5 }}>
              {r.company_name}
            </Text>
            <Text style={{ fontSize: 13, color: t.sub, marginBottom: 10 }}>
              {[r.statement_type, r.period, r.currency].filter(Boolean).join(' · ')}
            </Text>
            {r.investment_label && (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <View style={{ backgroundColor: ic, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 7 }}>
                  <Text style={{ color: '#fff', fontSize: 14, fontWeight: '900' }}>{r.investment_label}</Text>
                </View>
                {r.health_label && (
                  <View style={{ backgroundColor: sc + '22', borderRadius: 10, paddingHorizontal: 10, paddingVertical: 7 }}>
                    <Text style={{ color: sc, fontSize: 12, fontWeight: '700' }}>{r.health_label}</Text>
                  </View>
                )}
              </View>
            )}
          </View>

          {r.headline && (
            <View style={{ backgroundColor: t.accentBg, borderLeftWidth: 3, borderLeftColor: t.accent, borderRadius: 12, padding: 14, marginBottom: 14 }}>
              <Text style={{ fontSize: 14, fontWeight: '700', color: t.text, lineHeight: 22 }}>{r.headline}</Text>
            </View>
          )}

          <View style={[s.scoreCard, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '700', letterSpacing: 2, textTransform: 'uppercase', color: t.sub, marginBottom: 10 }}>
              Financial Health Score
            </Text>
            <View style={{ flexDirection: 'row', alignItems: 'flex-end' }}>
              <Text style={{ fontSize: 82, fontWeight: '900', lineHeight: 90, letterSpacing: -4, color: sc }}>{r.health_score}</Text>
              <Text style={{ fontSize: 28, fontWeight: '600', color: t.sub, marginBottom: 14 }}>/100</Text>
            </View>
            <View style={{ borderRadius: 24, paddingHorizontal: 22, paddingVertical: 7, backgroundColor: sc + '22', marginBottom: 14 }}>
              <Text style={{ fontSize: 16, fontWeight: '800', color: sc }}>{r.health_label}</Text>
            </View>
            {r.health_score_breakdown?.components?.length > 0 && (
              <View style={{ width: '100%', marginTop: 18 }}>
                <Text style={[s.cardTitle, { color: t.text, marginBottom: 12 }]}>Score Breakdown</Text>
                {r.health_score_breakdown.components.map((c: any, i: number) => (
                  <ScoreBar key={i} c={c} />
                ))}
              </View>
            )}
          </View>

          {r.executive_summary && (
            <Card title="📋 Executive Summary">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.executive_summary}</Text>
            </Card>
          )}

          {(r.for_long_term_investors || r.for_short_term_traders) && (
            <Card title="👥 Investor Perspectives">
              {r.for_long_term_investors && (
                <View style={{ marginBottom: 16 }}>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#22c55e', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 7 }}>🏛 Long-Term Investors</Text>
                  <Text style={{ fontSize: 13, lineHeight: 21, color: t.text }}>{r.for_long_term_investors}</Text>
                </View>
              )}
              {r.for_short_term_traders && (
                <View>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#f59e0b', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 7 }}>⚡ Short-Term Traders</Text>
                  <Text style={{ fontSize: 13, lineHeight: 21, color: t.text }}>{r.for_short_term_traders}</Text>
                </View>
              )}
            </Card>
          )}

          {r.bottom_line && (
            <Card title="💡 Bottom Line" leftBorder={ic}>
              <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 16 }}>
                <Text style={{ fontSize: 15, fontWeight: '700', lineHeight: 24, color: t.text }}>{r.bottom_line}</Text>
              </View>
            </Card>
          )}

          {r.investor_verdict && (
            <Card title="🎯 Investor Verdict" leftBorder={t.accent}>
              <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 16 }}>
                <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{r.investor_verdict}</Text>
              </View>
            </Card>
          )}

          {r.key_metrics?.filter((m: any) => safe(m?.current)).length > 0 && (
            <Card title="📊 Key Metrics">
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: t.border, marginBottom: 4 }}>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Metric</Text>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Current · Prev · Change · Signal</Text>
              </View>
              {r.key_metrics.map((m: any, i: number) => <MetricRow key={i} m={m} />)}
            </Card>
          )}

          {pa.analysis && (
            <Card title="💹 Profitability">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Net Margin" value={pa.net_margin_current} color="#22c55e" />
                <Stat label="EBITDA Margin" value={pa.ebitda_margin_current} color="#4F8AFF" />
                <Stat label="ROE" value={pa.roe} color="#22c55e" />
                <Stat label="ROA" value={pa.roa} color="#f59e0b" />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{pa.analysis}</Text>
            </Card>
          )}

          {lq.analysis && (
            <Card title="💧 Liquidity">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Current Ratio" value={lq.current_ratio} color="#4F8AFF" />
                <Stat label="Quick Ratio" value={lq.quick_ratio} color="#4F8AFF" />
                <Stat label="Cash Position" value={lq.cash_position} />
                <Stat label="Free Cash Flow" value={lq.free_cash_flow} color="#22c55e" />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{lq.analysis}</Text>
            </Card>
          )}

          {cfd.ocf_vs_pat_insight && (
            <Card title="🌊 Cash Flow Quality">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Operating CF" value={cfd.operating_cf} />
                <Stat label="Free CF" value={cfd.free_cash_flow} color="#22c55e" />
                <Stat label="Capex" value={cfd.capex} />
                {cfQualityLabel ? (
                  <View style={[s.stat, { backgroundColor: cfqColor(cfQualityLabel) + '20', borderColor: t.border }]}>
                    <Text style={{ fontSize: 14, fontWeight: '800', color: cfqColor(cfQualityLabel) }}>{cfQualityLabel}</Text>
                    <Text style={{ fontSize: 10, color: t.sub, marginTop: 4, fontWeight: '600' }}>Quality</Text>
                  </View>
                ) : null}
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{cfd.ocf_vs_pat_insight}</Text>
              {safe(cfd.investing_cf) && (
                <Text style={{ fontSize: 13, color: t.sub, marginTop: 8 }}>
                  Investing CF: {cfd.investing_cf}{safe(cfd.financing_cf) ? ` · Financing CF: ${cfd.financing_cf}` : ''}
                </Text>
              )}
            </Card>
          )}

          {bsd.debt_to_equity && (
            <Card title="🏗️ Balance Sheet Health">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="D/E Ratio" value={bsd.debt_to_equity} color="#f59e0b" />
                <Stat label="Interest Cover" value={bsd.interest_coverage} color="#22c55e" />
                <Stat label="Total Debt" value={bsd.total_debt} />
                <Stat label="Net Worth" value={bsd.net_worth} />
                {bsd.debt_comfort_level && (
                  <View style={[s.stat, { backgroundColor: debtColor(bsd.debt_comfort_level) + '20', borderColor: t.border }]}>
                    <Text style={{ fontSize: 13, fontWeight: '800', color: debtColor(bsd.debt_comfort_level) }}>{bsd.debt_comfort_level}</Text>
                    <Text style={{ fontSize: 10, color: t.sub, marginTop: 4, fontWeight: '600' }}>Debt Level</Text>
                  </View>
                )}
              </View>
              {safe(bsd.asset_quality) && <Text style={{ fontSize: 14, lineHeight: 22, color: t.text, marginBottom: 8 }}>{bsd.asset_quality}</Text>}
              {safe(bsd.debt_profile) && <Text style={{ fontSize: 14, lineHeight: 22, color: t.text, marginBottom: 8 }}>{bsd.debt_profile}</Text>}
              {safe(bsd.working_capital_insight) && <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{bsd.working_capital_insight}</Text>}
            </Card>
          )}

          {(gq.revenue_growth_context || gq.catalysts?.length || gq.headwinds?.length) && (
            <Card title="📈 Growth Quality">
              {safe(gq.revenue_growth_context) && (
                <View style={{ marginBottom: 10 }}>
                  <Text style={{ fontSize: 11, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Revenue</Text>
                  <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{gq.revenue_growth_context}</Text>
                </View>
              )}
              {safe(gq.profit_growth_context) && (
                <View style={{ marginBottom: 10 }}>
                  <Text style={{ fontSize: 11, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Profit</Text>
                  <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{gq.profit_growth_context}</Text>
                </View>
              )}
              {safe(gq.margin_trend) && (
                <View style={{ marginBottom: 10 }}>
                  <Text style={{ fontSize: 11, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Margin Trend</Text>
                  <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{gq.margin_trend}</Text>
                </View>
              )}
              {safe(gq.growth_outlook) && (
                <View style={{ backgroundColor: t.accentBg, borderLeftWidth: 3, borderLeftColor: t.accent, borderRadius: 10, padding: 12, marginBottom: 14 }}>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: t.accent, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 5 }}>Outlook</Text>
                  <Text style={{ fontSize: 13, lineHeight: 20, color: t.text }}>{gq.growth_outlook}</Text>
                </View>
              )}
              {gq.catalysts?.length > 0 && (
                <>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#22c55e', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Catalysts</Text>
                  {gq.catalysts.map((x: any, i: number) => <Dot key={i} text={x} color="#22c55e" />)}
                </>
              )}
              {gq.headwinds?.length > 0 && (
                <>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#ef4444', textTransform: 'uppercase', letterSpacing: 1, marginTop: 10, marginBottom: 8 }}>Headwinds</Text>
                  {gq.headwinds.map((x: any, i: number) => <Dot key={i} text={x} color="#ef4444" />)}
                </>
              )}
            </Card>
          )}

          {indc.competitive_position && (
            <Card title="🏭 Industry Context">
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text, marginBottom: 14 }}>{indc.competitive_position}</Text>
              {indc.sector_tailwinds?.length > 0 && (
                <>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#22c55e', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Tailwinds</Text>
                  {indc.sector_tailwinds.map((x: any, i: number) => <Dot key={i} text={x} color="#22c55e" />)}
                </>
              )}
              {indc.sector_headwinds?.length > 0 && (
                <>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#ef4444', textTransform: 'uppercase', letterSpacing: 1, marginTop: 10, marginBottom: 8 }}>Headwinds</Text>
                  {indc.sector_headwinds.map((x: any, i: number) => <Dot key={i} text={x} color="#ef4444" />)}
                </>
              )}
              {safe(indc.peer_benchmarks) && (
                <View style={{ backgroundColor: t.cardAlt, borderRadius: 10, padding: 12, marginTop: 12 }}>
                  <Text style={{ fontSize: 11, fontWeight: '700', color: t.sub, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Peer Benchmarks</Text>
                  <Text style={{ fontSize: 13, lineHeight: 20, color: t.text }}>{indc.peer_benchmarks}</Text>
                </View>
              )}
              {safe(indc.regulatory_environment) && (
                <Text style={{ fontSize: 12, color: t.sub, marginTop: 10, lineHeight: 19 }}>{indc.regulatory_environment}</Text>
              )}
            </Card>
          )}

          {r.strengths_and_moats?.length > 0 && (
            <Card title="✅ Strengths & Moats">
              {r.strengths_and_moats.map((h: any, i: number) => <Dot key={i} text={h} color="#22c55e" />)}
            </Card>
          )}
          {r.red_flags?.length > 0 && (
            <Card title="🚩 Red Flags">
              {r.red_flags.map((f: any, i: number) => <Dot key={i} text={f} color="#ef4444" />)}
            </Card>
          )}
          {r.highlights?.length > 0 && (
            <Card title="🌟 Highlights">
              {r.highlights.map((h: any, i: number) => <Dot key={i} text={h} color="#22c55e" />)}
            </Card>
          )}
          {r.risks?.length > 0 && (
            <Card title="⚠️ Key Risks">
              {r.risks.map((x: any, i: number) => <Dot key={i} text={x} color="#ef4444" />)}
            </Card>
          )}
          {r.key_monitorables?.length > 0 && (
            <Card title="🔭 Key Monitorables">
              {r.key_monitorables.map((x: any, i: number) => <Dot key={i} text={x} color={t.accent} />)}
            </Card>
          )}
          {r.what_to_watch?.length > 0 && (
            <Card title="👁️ What to Watch">
              {r.what_to_watch.map((x: any, i: number) => <Dot key={i} text={x} color={t.accent} />)}
            </Card>
          )}

          {faq.length > 0 && (
            <Card title="❓ Investor FAQ">
              {faq.map((f: any, i: number) => (
                <View key={i} style={{ marginBottom: i < faq.length - 1 ? 18 : 0 }}>
                  <Text style={{ fontSize: 13, fontWeight: '700', color: t.text, marginBottom: 5 }}>
                    {f.question || String(f)}
                  </Text>
                  {f.answer && (
                    <Text style={{ fontSize: 13, lineHeight: 21, color: t.sub }}>{f.answer}</Text>
                  )}
                </View>
              ))}
            </Card>
          )}

          <View style={[s.sharePanel, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', color: t.sub, textAlign: 'center', marginBottom: 18 }}>
              SAVE & SHARE
            </Text>
            <TouchableOpacity
              style={[s.pdfBtn, { backgroundColor: t.accent, opacity: downloading ? 0.7 : 1 }]}
              onPress={handleDownloadPDF}
              disabled={downloading}
            >
              {downloading ? <ActivityIndicator color="#fff" /> : (
                <>
                  <Text style={{ fontSize: 22 }}>⬇️</Text>
                  <View>
                    <Text style={{ color: '#fff', fontSize: 16, fontWeight: '800' }}>Download Full PDF Report</Text>
                    <Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, marginTop: 2 }}>
                      Institutional-grade · {dark ? 'Dark' : 'Light'} theme
                    </Text>
                  </View>
                </>
              )}
            </TouchableOpacity>
            <View style={{ flexDirection: 'row', gap: 10, marginBottom: 12 }}>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleWhatsApp}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>💬</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>WhatsApp</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: '#000' }]} onPress={handleTwitter}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>𝕏</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Twitter</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.shareBtn, { backgroundColor: t.accent }]} onPress={handleShare}>
                <Text style={{ fontSize: 18, marginBottom: 3 }}>📤</Text>
                <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Share</Text>
              </TouchableOpacity>
            </View>
            <TouchableOpacity
              style={[s.copyBtn, { borderColor: copied ? '#22c55e' : t.accent, backgroundColor: copied ? '#22c55e15' : t.accentBg }]}
              onPress={handleCopyLink}
            >
              <Text style={{ color: copied ? '#22c55e' : t.accent, fontSize: 15, fontWeight: '700' }}>
                {copied ? '✅ Link Copied!' : '🔗 Copy Shareable Link'}
              </Text>
              {!copied && (
                <Text style={{ color: t.sub, fontSize: 11, marginTop: 4, textAlign: 'center' }}>
                  Anyone can open this — no login needed
                </Text>
              )}
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={[s.backBtn, { borderColor: t.border }]} onPress={handleBack}>
            <Text style={{ color: t.sub, fontSize: 14, fontWeight: '600' }}>← Back</Text>
          </TouchableOpacity>
          <View style={{ height: 60 }} />
        </View>
      </Animated.ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  btn:         { borderRadius: 14, padding: 16, paddingHorizontal: 32 },
  btnTxt:      { color: '#fff', fontSize: 15, fontWeight: '700' },
  topBar:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 56, paddingBottom: 16, borderBottomWidth: 1 },
  card:        { borderRadius: 20, padding: 18, marginBottom: 14, borderWidth: 1, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 10, elevation: 3 },
  cardTitle:   { fontSize: 15, fontWeight: '800', marginBottom: 14, letterSpacing: -0.3 },
  scoreCard:   { borderRadius: 22, padding: 24, alignItems: 'center', marginBottom: 14, borderWidth: 1 },
  scoreBarBox: { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  row:         { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 12, borderBottomWidth: 1 },
  stat:        { borderRadius: 14, padding: 14, minWidth: '30%', flex: 1, alignItems: 'center', borderWidth: 1 },
  dotRow:      { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 12 },
  dotCircle:   { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1, flexShrink: 0 },
  sharePanel:  { borderRadius: 22, padding: 20, marginBottom: 14, borderWidth: 1 },
  pdfBtn:      { borderRadius: 16, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 14 },
  shareBtn:    { flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  copyBtn:     { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1.5 },
  backBtn:     { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1, marginBottom: 4 },
});
