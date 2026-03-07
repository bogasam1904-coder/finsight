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

// ─── helpers ────────────────────────────────────────────────────────────────
const val = (obj: any, ...keys: string[]) => {
  for (const k of keys) { if (obj?.[k] && obj[k] !== 'N/A' && obj[k] !== '') return obj[k]; }
  return null;
};
const pct = (obj: any) => val(obj, 'yoy_chg_pct', 'change_pct');
const curr = (obj: any) => val(obj, 'current');
const prev = (obj: any) => val(obj, 'previous');

// ─── PDF HTML generator ──────────────────────────────────────────────────────
function pdfHTML(r: any, dark: boolean): string {
  const sc = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : '#ef4444';
  const d = dark;
  const bg   = d ? '#060B18' : '#ffffff';
  const cardBg = d ? '#0D1426' : '#f8faff';
  const textC  = d ? '#F0F4FF' : '#0A0E1A';
  const subC   = d ? '#6B82A8' : '#6b7280';
  const borderC = d ? '#1E2D4A' : '#e5e7eb';
  const accentC = d ? '#4F8AFF' : '#0052FF';

  const section = (title: string, body: string) =>
    `<div style="margin-bottom:28px;page-break-inside:avoid">
      <div style="font-size:13px;font-weight:800;color:${textC};margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid ${borderC};text-transform:uppercase;letter-spacing:1px">${title}</div>
      ${body}
    </div>`;

  const pill = (label: string, color: string) =>
    `<span style="display:inline-block;background:${color}22;color:${color};font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;margin-right:6px">${label}</span>`;

  const table = (rows: string) =>
    `<table style="width:100%;border-collapse:collapse;font-size:13px">${rows}</table>`;

  const th = (label: string) =>
    `<th style="background:${cardBg};padding:8px 12px;font-size:11px;color:${subC};text-align:left;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid ${borderC}">${label}</th>`;

  const td = (val: string, right = false, bold = false, color = '') =>
    `<td style="padding:9px 12px;border-bottom:1px solid ${borderC};${right ? 'text-align:right;' : ''}${bold ? 'font-weight:700;' : ''}color:${color || textC};font-size:13px">${val || '—'}</td>`;

  const statBox = (label: string, value: string, color = accentC) =>
    `<div style="background:${cardBg};border:1px solid ${borderC};border-radius:10px;padding:14px 16px;display:inline-block;min-width:120px;margin:4px">
      <div style="font-size:18px;font-weight:800;color:${color}">${value || '—'}</div>
      <div style="font-size:11px;color:${subC};margin-top:4px">${label}</div>
    </div>`;

  const li = (arr: any[]) =>
    (arr || []).filter(Boolean).map(x =>
      `<li style="margin-bottom:7px;font-size:13px;color:${textC};line-height:1.7">${x}</li>`
    ).join('');

  // ── Rating badge ──
  const ratingColor = r.analyst_rating === 'BUY' ? '#22c55e' : r.analyst_rating === 'SELL' ? '#ef4444' : '#f59e0b';
  const ratingBadge = r.analyst_rating
    ? `<div style="display:inline-block;background:${ratingColor};color:#fff;font-size:14px;font-weight:900;padding:6px 20px;border-radius:8px;margin-left:12px">${r.analyst_rating}</div>`
    : '';

  // ── Score breakdown ──
  const breakdown = r.health_score_breakdown || {};
  const bKeys = ['revenue_growth','net_margin','ebitda_margin','debt_to_equity','current_ratio','ocf_quality','roe','eps_growth'];
  const scoreRows = bKeys.map(k => {
    const c = breakdown[k];
    if (!c) return '';
    const col = c.pts >= c.max * 0.7 ? '#22c55e' : c.pts >= c.max * 0.4 ? '#f59e0b' : '#ef4444';
    const pct = c.max > 0 ? Math.round((c.pts / c.max) * 100) : 0;
    const label = k.replace(/_/g,' ').replace(/\b\w/g, (l: string) => l.toUpperCase());
    return `<tr>
      <td style="padding:10px 12px;border-bottom:1px solid ${borderC};color:${textC};font-size:13px;font-weight:600">${label}</td>
      <td style="padding:10px 12px;border-bottom:1px solid ${borderC};color:${subC};font-size:12px">${c.value || '—'}</td>
      <td style="padding:10px 12px;border-bottom:1px solid ${borderC}">
        <div style="background:${borderC};border-radius:3px;height:5px;width:100px">
          <div style="background:${col};height:5px;border-radius:3px;width:${pct}%"></div>
        </div>
      </td>
      <td style="padding:10px 12px;border-bottom:1px solid ${borderC};text-align:right;font-weight:800;color:${col}">${c.pts}/${c.max}</td>
    </tr><tr><td colspan="4" style="padding:4px 12px 10px;border-bottom:1px solid ${borderC};font-size:11px;color:${subC}">${c.reason || ''}</td></tr>`;
  }).join('');

  // ── Key metrics table ──
  const metricRows = (r.key_metrics || [])
    .filter((m: any) => m.current && m.current !== 'N/A' && m.current !== '')
    .map((m: any) => `<tr>
      ${td(m.metric, false, true)}
      ${td(m.current, true, true)}
      ${td(m.previous || '—', true)}
      ${td(m.change_pct || m.change || '—', true, true, m.change_pct?.includes('-') ? '#ef4444' : '#22c55e')}
    </tr>`).join('');

  // ── Income statement table ──
  const is = r.income_statement || {};
  const isFields = [
    ['Revenue', is.revenue], ['Other Income', is.other_income], ['Total Income', is.total_income],
    ['COGS', is.cost_of_goods_sold], ['Gross Profit', is.gross_profit], ['Employee Costs', is.employee_costs],
    ['EBITDA', is.ebitda], ['Depreciation', is.depreciation], ['EBIT', is.ebit],
    ['Finance Cost', is.finance_cost], ['PBT', is.pbt], ['Tax', is.tax_expense],
    ['PAT', is.pat], ['EPS Basic', is.eps_basic], ['EPS Diluted', is.eps_diluted],
  ];
  const isRows = isFields.filter(([, obj]) => curr(obj)).map(([label, obj]: any) =>
    `<tr>${td(label,false,true)}${td(curr(obj)||'—',true,true)}${td(prev(obj)||'—',true)}${td(pct(obj)||'—',true,false,pct(obj)?.includes('-')?'#ef4444':'#22c55e')}</tr>`
  ).join('');

  // ── Balance sheet ──
  const bs = r.balance_sheet || {};
  const bsFields = [
    ['Total Assets', bs.total_assets], ['Current Assets', bs.current_assets],
    ['Inventories', bs.inventories], ['Trade Receivables', bs.trade_receivables],
    ['Cash & Equivalents', bs.cash_equivalents], ['Total Equity', bs.total_equity],
    ['Reserves & Surplus', bs.reserves_surplus], ['Total Borrowings', bs.total_borrowings],
    ['LT Borrowings', bs.long_term_borrowings], ['ST Borrowings', bs.short_term_borrowings],
    ['Trade Payables', bs.trade_payables], ['Current Liabilities', bs.current_liabilities],
  ];
  const bsRows = bsFields.filter(([, obj]) => curr(obj)).map(([label, obj]: any) =>
    `<tr>${td(label,false,true)}${td(curr(obj)||'—',true,true)}${td(prev(obj)||'—',true)}${td(pct(obj)||'—',true,false,pct(obj)?.includes('-')?'#ef4444':'#22c55e')}</tr>`
  ).join('');

  // ── Cash flow ──
  const cf = r.cash_flow_statement || {};
  const cfFields = [
    ['Operating CF', cf.operating_cash_flow], ['Investing CF', cf.investing_cash_flow],
    ['Financing CF', cf.financing_cash_flow], ['Capex', cf.capex], ['Free Cash Flow', cf.free_cash_flow],
  ];
  const cfRows = cfFields.filter(([, obj]) => curr(obj)).map(([label, obj]: any) =>
    `<tr>${td(label,false,true)}${td(curr(obj)||'—',true,true)}${td(prev(obj)||'—',true)}<td style="padding:9px 12px;border-bottom:1px solid ${borderC}"></td></tr>`
  ).join('');

  // ── Ratios ──
  const pa = r.profitability_analysis || {};
  const la = r.liquidity_analysis || {};
  const lv = r.leverage_analysis || {};
  const rr = r.rates_of_return || {};
  const ea = r.efficiency_analysis || {};

  // ── Investment thesis ──
  const thesis = r.investment_thesis || {};

  // ── Segments ──
  const sa = r.segment_analysis || {};
  const segRows = (sa.segments || []).filter((s: any) => s.name).map((s: any) =>
    `<tr>${td(s.name,false,true)}${td(s.revenue||'—',true)}${td(s.revenue_pct_total||'—',true)}${td(s.ebit||'—',true)}${td(s.ebit_margin||'—',true)}</tr>`
  ).join('');

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;background:${bg};color:${textC};-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{max-width:860px;margin:0 auto;padding:48px 40px}
  table{width:100%;border-collapse:collapse}
  ul{padding-left:18px;margin:6px 0}
  @page{margin:0.5in}
  @media print{.page{padding:0}}
</style></head>
<body><div class="page">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:36px;padding-bottom:24px;border-bottom:3px solid ${accentC}">
    <div>
      <div style="font-size:22px;font-weight:900;color:${accentC};letter-spacing:-0.5px">📊 FinSight</div>
      <div style="font-size:12px;color:${subC};margin-top:4px">AI Equity Research Report</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:22px;font-weight:900;color:${textC}">${r.company_name || 'Analysis'}${ratingBadge}</div>
      <div style="font-size:13px;color:${subC};margin-top:5px">${r.ticker || ''} ${r.exchange ? '· ' + r.exchange : ''} ${r.statement_type ? '· ' + r.statement_type : ''}</div>
      <div style="font-size:13px;color:${subC};margin-top:3px">${r.period || ''} · ${r.unit || ''} · ${r.reporting_currency || 'INR'}</div>
      <div style="font-size:11px;color:${subC};margin-top:5px">Generated ${new Date().toLocaleDateString('en-IN',{day:'numeric',month:'long',year:'numeric'})}</div>
    </div>
  </div>

  <!-- Headline -->
  ${r.headline ? `<div style="font-size:16px;font-weight:700;color:${textC};background:${cardBg};border-left:4px solid ${accentC};padding:14px 18px;border-radius:0 10px 10px 0;margin-bottom:28px;line-height:1.5">${r.headline}</div>` : ''}

  <!-- Health Score -->
  <div style="text-align:center;background:${cardBg};border-radius:18px;padding:36px;margin-bottom:28px;border:1px solid ${borderC}">
    <div style="font-size:11px;color:${subC};text-transform:uppercase;letter-spacing:3px;margin-bottom:12px">Financial Health Score</div>
    <div style="font-size:90px;font-weight:900;color:${sc};line-height:1;letter-spacing:-4px">${r.health_score}<span style="font-size:32px;color:${subC}">/100</span></div>
    ${pill(r.health_label || '', sc)}
    ${r.analyst_rating ? `<div style="margin-top:16px">${pill('Analyst: ' + r.analyst_rating, ratingColor)}</div>` : ''}
  </div>

  <!-- Score Breakdown -->
  ${scoreRows ? section('📐 Score Breakdown', `<table><thead><tr>${th('Component')}${th('Value')}${th('Score Bar')}${th('Pts')}</tr></thead><tbody>${scoreRows}</tbody></table>`) : ''}

  <!-- Analyst Rating Rationale -->
  ${r.analyst_rating_rationale ? section('🎯 Investment Recommendation', `<div style="background:${cardBg};border-left:4px solid ${ratingColor};padding:14px 18px;border-radius:0 10px 10px 0;font-size:14px;line-height:1.8;color:${textC}">${r.analyst_rating_rationale}</div>`) : ''}

  <!-- Executive Summary -->
  ${r.executive_summary ? section('📋 Executive Summary', `<p style="font-size:14px;line-height:1.9;color:${textC}">${r.executive_summary}</p>`) : ''}

  <!-- Investment Thesis -->
  ${(thesis.bull_case || thesis.bear_case) ? section('⚖️ Investment Thesis', `
    ${thesis.bull_case ? `<div style="margin-bottom:14px"><div style="font-size:12px;font-weight:800;color:#22c55e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">🐂 Bull Case</div><p style="font-size:13px;line-height:1.8;color:${textC}">${thesis.bull_case}</p></div>` : ''}
    ${thesis.bear_case ? `<div style="margin-bottom:14px"><div style="font-size:12px;font-weight:800;color:#ef4444;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">🐻 Bear Case</div><p style="font-size:13px;line-height:1.8;color:${textC}">${thesis.bear_case}</p></div>` : ''}
    ${thesis.key_monitorables?.length ? `<div><div style="font-size:12px;font-weight:800;color:${subC};text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Key Monitorables</div><ul>${li(thesis.key_monitorables)}</ul></div>` : ''}
  `) : ''}

  <!-- Key Metrics -->
  ${metricRows ? section('📊 Key Metrics', table(`<thead><tr>${th('Metric')}${th('Current')}${th('Previous')}${th('YoY Δ')}</tr></thead><tbody>${metricRows}</tbody>`)) : ''}

  <!-- Income Statement -->
  ${isRows ? section('📈 Income Statement', table(`<thead><tr>${th('Line Item')}${th('Current')}${th('Previous')}${th('YoY %')}</tr></thead><tbody>${isRows}</tbody>`)) : ''}

  <!-- Balance Sheet -->
  ${bsRows ? section('🏦 Balance Sheet', table(`<thead><tr>${th('Line Item')}${th('Current')}${th('Previous')}${th('YoY %')}</tr></thead><tbody>${bsRows}</tbody>`)) : ''}

  <!-- Cash Flow -->
  ${cfRows ? section('💰 Cash Flow Statement', table(`<thead><tr>${th('Line Item')}${th('Current')}${th('Previous')}${th('')}</tr></thead><tbody>${cfRows}</tbody>`)) : ''}

  <!-- Profitability -->
  ${pa.commentary ? section('💹 Profitability Analysis', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${pa.gross_margin_pct ? statBox('Gross Margin', pa.gross_margin_pct + '%', '#22c55e') : ''}
      ${pa.ebitda_margin_pct ? statBox('EBITDA Margin', pa.ebitda_margin_pct + '%', '#4F8AFF') : ''}
      ${pa.net_profit_margin_pct ? statBox('Net Margin', pa.net_profit_margin_pct + '%', '#f59e0b') : ''}
      ${pa.roe_pct ? statBox('ROE', pa.roe_pct + '%', '#22c55e') : ''}
      ${pa.roa_pct ? statBox('ROA', pa.roa_pct + '%', '#22c55e') : ''}
      ${pa.roic_pct ? statBox('ROIC', pa.roic_pct + '%', '#22c55e') : ''}
      ${pa.roce_pct ? statBox('ROCE', pa.roce_pct + '%', '#22c55e') : ''}
    </div>
    <p style="font-size:13px;line-height:1.8;color:${textC}">${pa.commentary}</p>
  `) : ''}

  <!-- Leverage -->
  ${lv.commentary ? section('🏗️ Leverage & Debt', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${lv.debt_to_equity ? statBox('D/E Ratio', lv.debt_to_equity, '#f59e0b') : ''}
      ${lv.net_debt_to_ebitda ? statBox('Net Debt/EBITDA', lv.net_debt_to_ebitda, '#f59e0b') : ''}
      ${lv.interest_coverage_ratio ? statBox('Interest Cover', lv.interest_coverage_ratio + 'x', '#22c55e') : ''}
      ${lv.net_debt ? statBox('Net Debt', lv.net_debt) : ''}
    </div>
    <p style="font-size:13px;line-height:1.8;color:${textC}">${lv.commentary}</p>
  `) : ''}

  <!-- Liquidity -->
  ${la.commentary ? section('💧 Liquidity Analysis', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${la.current_ratio ? statBox('Current Ratio', la.current_ratio, '#4F8AFF') : ''}
      ${la.quick_ratio ? statBox('Quick Ratio', la.quick_ratio, '#4F8AFF') : ''}
      ${la.cash_ratio ? statBox('Cash Ratio', la.cash_ratio, '#4F8AFF') : ''}
      ${la.net_working_capital ? statBox('Net Working Capital', la.net_working_capital) : ''}
    </div>
    <p style="font-size:13px;line-height:1.8;color:${textC}">${la.commentary}</p>
  `) : ''}

  <!-- Cash Flow Analysis -->
  ${r.cash_flow_analysis?.commentary ? section('🌊 Cash Flow Quality', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${r.cash_flow_analysis.ocf_to_pat_ratio ? statBox('OCF/PAT', r.cash_flow_analysis.ocf_to_pat_ratio + 'x') : ''}
      ${r.cash_flow_analysis.fcf_margin_pct ? statBox('FCF Margin', r.cash_flow_analysis.fcf_margin_pct + '%') : ''}
      ${r.cash_flow_analysis.cash_quality ? `<div style="background:${ r.cash_flow_analysis.cash_quality==='Strong'?'#22c55e22':'#f59e0b22'};border:1px solid ${borderC};border-radius:10px;padding:14px 16px;display:inline-block"><div style="font-size:15px;font-weight:800;color:${ r.cash_flow_analysis.cash_quality==='Strong'?'#22c55e':'#f59e0b'}">${r.cash_flow_analysis.cash_quality}</div><div style="font-size:11px;color:${subC};margin-top:4px">Cash Quality</div></div>` : ''}
    </div>
    <p style="font-size:13px;line-height:1.8;color:${textC}">${r.cash_flow_analysis.commentary}</p>
  `) : ''}

  <!-- Efficiency -->
  ${ea.commentary ? section('⚙️ Efficiency Analysis', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${ea.inventory_turnover_days ? statBox('Inventory Days', ea.inventory_turnover_days) : ''}
      ${ea.receivables_turnover_days ? statBox('Receivable Days', ea.receivables_turnover_days) : ''}
      ${ea.payables_turnover_days ? statBox('Payable Days', ea.payables_turnover_days) : ''}
      ${ea.cash_conversion_cycle_days ? statBox('CCC Days', ea.cash_conversion_cycle_days) : ''}
      ${ea.asset_turnover ? statBox('Asset Turnover', ea.asset_turnover + 'x') : ''}
    </div>
    <p style="font-size:13px;line-height:1.8;color:${textC}">${ea.commentary}</p>
  `) : ''}

  <!-- Segment Analysis -->
  ${segRows ? section('🏢 Segment Analysis', `
    ${table(`<thead><tr>${th('Segment')}${th('Revenue')}${th('% of Total')}${th('EBIT')}${th('EBIT Margin')}</tr></thead><tbody>${segRows}</tbody>`)}
    ${sa.commentary ? `<p style="font-size:13px;line-height:1.8;color:${textC};margin-top:12px">${sa.commentary}</p>` : ''}
  `) : ''}

  <!-- Horizontal Analysis -->
  ${r.horizontal_analysis?.notable_trends?.length ? section('📉 Trend Analysis', `
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
      ${r.horizontal_analysis.revenue_growth_yoy_pct ? statBox('Revenue Growth', r.horizontal_analysis.revenue_growth_yoy_pct + '%', '#22c55e') : ''}
      ${r.horizontal_analysis.pat_growth_yoy_pct ? statBox('PAT Growth', r.horizontal_analysis.pat_growth_yoy_pct + '%', '#22c55e') : ''}
      ${r.horizontal_analysis.eps_growth_yoy_pct ? statBox('EPS Growth', r.horizontal_analysis.eps_growth_yoy_pct + '%', '#22c55e') : ''}
    </div>
    <ul>${li(r.horizontal_analysis.notable_trends)}</ul>
  `) : ''}

  <!-- Management Commentary -->
  ${r.management_commentary?.guidance || r.management_commentary?.key_developments?.length ? section('🎙️ Management Commentary', `
    ${r.management_commentary.guidance ? `<div style="background:${cardBg};border-left:4px solid ${accentC};padding:12px 16px;border-radius:0 10px 10px 0;margin-bottom:12px"><div style="font-size:11px;font-weight:800;color:${accentC};text-transform:uppercase;letter-spacing:1px;margin-bottom:5px">Guidance</div><p style="font-size:13px;line-height:1.8;color:${textC}">${r.management_commentary.guidance}</p></div>` : ''}
    ${r.management_commentary.key_developments?.length ? `<ul>${li(r.management_commentary.key_developments)}</ul>` : ''}
  `) : ''}

  <!-- Highlights + Risks + Watch -->
  ${r.highlights?.length ? section('✅ Key Strengths', `<ul>${li(r.highlights)}</ul>`) : ''}
  ${r.risks?.length ? section('⚠️ Key Risks', `<ul>${li(r.risks)}</ul>`) : ''}
  ${r.what_to_watch?.length ? section('🔭 What to Watch', `<ul>${li(r.what_to_watch)}</ul>`) : ''}

  <!-- Peer Context -->
  ${r.peer_context ? section('🔗 Peer Context', `<p style="font-size:13px;line-height:1.8;color:${textC}">${r.peer_context}</p>`) : ''}

  <!-- Investor Verdict -->
  ${r.investor_verdict ? section('💡 Investor Verdict', `<div style="background:${cardBg};border-left:4px solid ${accentC};padding:16px 20px;border-radius:0 12px 12px 0;font-size:14px;line-height:1.9;color:${textC}">${r.investor_verdict}</div>`) : ''}

  <!-- Footer -->
  <div style="text-align:center;color:${subC};font-size:11px;margin-top:48px;padding-top:20px;border-top:1px solid ${borderC}">
    Generated by FinSight · finsight-vert.vercel.app · ${dark ? 'Dark' : 'Light'} Theme · Not financial advice
  </div>

</div></body></html>`;
}

// ─── Main component ──────────────────────────────────────────────────────────
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
        const res2 = await fetch(`${BACKEND}/api/public/analyses/${id}`);
        if (res2.ok) {
          setAnalysis(await res2.json());
          Animated.timing(fadeAnim, { toValue: 1, duration: 500, useNativeDriver: false }).start();
        } else { setAnalysis(null); }
      } catch { setAnalysis(null); }
    } finally { setLoading(false); }
  };

  const handleDownloadPDF = async () => {
    if (!analysis?.result) return;
    setDownloading(true);
    try {
      const company = (analysis.result.company_name || 'FinSight').replace(/[^a-z0-9]/gi, '_');
      const html = pdfHTML(analysis.result, dark);
      if (Platform.OS === 'web') {
        const response = await fetch(`${BACKEND}/api/generate-pdf`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/pdf' },
          body: JSON.stringify({ html }),
        });
        if (!response.ok) throw new Error(`PDF generation failed (${response.status})`);
        const blob = await response.blob();
        if (blob.size < 1000) throw new Error('PDF too small — generation may have failed');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `${company}_Analysis.pdf`;
        document.body.appendChild(a); a.click();
        setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
      } else {
        const [PrintModule, SharingModule] = await Promise.all([import('expo-print'), import('expo-sharing')]);
        const { uri } = await PrintModule.printToFileAsync({ html, base64: false });
        if (await SharingModule.isAvailableAsync()) {
          await SharingModule.shareAsync(uri, { mimeType: 'application/pdf', dialogTitle: `Save ${company}.pdf`, UTI: 'com.adobe.pdf' });
        }
      }
    } catch (e: any) {
      Alert.alert('Download Failed', e.message || 'Could not generate PDF.');
    } finally { setDownloading(false); }
  };

  const shareUrl = `https://finsight-vert.vercel.app/share/${id}`;

  const handleCopyLink = async () => {
    if (Platform.OS === 'web' && navigator?.clipboard) await navigator.clipboard.writeText(shareUrl).catch(() => {});
    else { try { await Share.share({ message: shareUrl }); } catch {} }
    setCopied(true); setTimeout(() => setCopied(false), 3000);
  };

  const handleWhatsAppShare = () => {
    const r = analysis?.result;
    if (!r) return;
    const msg = `📊 *${r.company_name}* Financial Analysis\n\n💯 Health Score: *${r.health_score}/100* (${r.health_label})\n${r.analyst_rating ? `🎯 Rating: *${r.analyst_rating}*\n` : ''}\n${(r.investor_verdict || r.executive_summary || '').substring(0, 200)}\n\n📱 Full analysis:\n${shareUrl}\n\n_Powered by FinSight_`;
    const url = `https://wa.me/?text=${encodeURIComponent(msg)}`;
    Platform.OS === 'web' ? window.open(url, '_blank') : Linking.openURL(url).catch(() => Alert.alert('Error', 'Could not open WhatsApp'));
  };

  const handleTwitterShare = () => {
    const r = analysis?.result;
    if (!r) return;
    const tweet = `📊 ${r.company_name} — Health: ${r.health_score}/100 (${r.health_label})${r.analyst_rating ? ` · ${r.analyst_rating}` : ''}\n\n${(r.investor_verdict || '').substring(0, 120)}...\n\nFull analysis:`;
    const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweet)}&url=${encodeURIComponent(shareUrl)}`;
    Platform.OS === 'web' ? window.open(url, '_blank') : Linking.openURL(url).catch(() => {});
  };

  const handleGenericShare = async () => {
    const r = analysis?.result;
    if (!r) return;
    try { await Share.share({ message: `📊 ${r.company_name} — ${r.health_score}/100\n${r.investor_verdict || ''}\n\n${shareUrl}`, title: `${r.company_name} — Financial Analysis` }); } catch {}
  };

  const handleBack = () => { if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); };

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
      <Text style={{ color: t.textSub, fontSize: 14, textAlign: 'center', lineHeight: 22, marginBottom: 28, paddingHorizontal: 32 }}>This analysis may have been deleted or the link is incorrect.</Text>
      <TouchableOpacity style={[gs.btn, { backgroundColor: t.accent }]} onPress={handleBack}><Text style={gs.btnText}>← Go Back</Text></TouchableOpacity>
    </View>
  );

  const r = analysis.result;
  const sc = r.health_score >= 80 ? '#22c55e' : r.health_score >= 60 ? '#f59e0b' : r.health_score >= 40 ? '#ef4444' : '#dc2626';
  const ratingColor = r.analyst_rating === 'BUY' ? '#22c55e' : r.analyst_rating === 'SELL' ? '#ef4444' : '#f59e0b';
  const breakdown = r.health_score_breakdown || {};
  const bKeys = ['revenue_growth','net_margin','ebitda_margin','debt_to_equity','current_ratio','ocf_quality','roe','eps_growth'];

  // ── Sub-components ──
  const Card = ({ title, leftBorder, children }: any) => (
    <View style={[gs.card, { backgroundColor: t.card, borderColor: leftBorder ? 'transparent' : t.border, borderLeftColor: leftBorder || t.border, borderLeftWidth: leftBorder ? 3 : 1 }]}>
      {title && <Text style={[gs.cardTitle, { color: t.text }]}>{title}</Text>}
      {children}
    </View>
  );

  const Stat = ({ label, value, color }: any) => {
    if (!value || value === 'N/A' || value === '') return null;
    return (
      <View style={[gs.statBox, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <Text style={{ fontSize: 16, fontWeight: '800', color: color || t.accent }}>{value}</Text>
        <Text style={{ fontSize: 10, color: t.textSub, marginTop: 4, textAlign: 'center', fontWeight: '600' }}>{label}</Text>
      </View>
    );
  };

  const MetricRow = ({ m }: any) => {
    if (!m?.current || m.current === 'N/A' || m.current === '') return null;
    const chg = m.change_pct || m.change || '';
    const isNeg = chg.includes('-');
    return (
      <View style={[gs.row, { borderBottomColor: t.border }]}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <Text style={{ fontSize: 13, fontWeight: '600', color: t.text }}>{m.metric || m.label}</Text>
          {m.comment && m.comment !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2, fontStyle: 'italic' }}>{m.comment}</Text>}
        </View>
        <View style={{ alignItems: 'flex-end', minWidth: 110 }}>
          <Text style={{ fontSize: 14, fontWeight: '800', color: t.text }}>{m.current}</Text>
          {m.previous && m.previous !== 'N/A' && <Text style={{ fontSize: 11, color: t.textSub, marginTop: 2 }}>vs {m.previous}</Text>}
          {chg && chg !== 'N/A' && <Text style={{ fontSize: 12, fontWeight: '700', marginTop: 2, color: isNeg ? '#ef4444' : '#22c55e' }}>{isNeg ? '▼' : '▲'} {chg}</Text>}
        </View>
      </View>
    );
  };

  const ISRow = ({ label, obj }: any) => {
    const c = curr(obj); if (!c) return null;
    const p = prev(obj); const chg = pct(obj);
    const isNeg = chg?.includes('-');
    return (
      <View style={[gs.row, { borderBottomColor: t.border }]}>
        <Text style={{ flex: 1, fontSize: 13, fontWeight: '600', color: t.text }}>{label}</Text>
        <View style={{ alignItems: 'flex-end', minWidth: 140 }}>
          <Text style={{ fontSize: 13, fontWeight: '800', color: t.text }}>{c}</Text>
          {p && <Text style={{ fontSize: 11, color: t.textSub }}>vs {p}</Text>}
          {chg && <Text style={{ fontSize: 11, fontWeight: '700', color: isNeg ? '#ef4444' : '#22c55e' }}>{isNeg ? '▼' : '▲'} {chg}</Text>}
        </View>
      </View>
    );
  };

  const ScoreBar = ({ k }: any) => {
    const c = breakdown[k]; if (!c) return null;
    const col = c.pts >= c.max * 0.7 ? '#22c55e' : c.pts >= c.max * 0.4 ? '#f59e0b' : '#ef4444';
    const pct2 = c.max > 0 ? (c.pts / c.max) * 100 : 0;
    const label = k.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase());
    return (
      <View style={[gs.scoreBar, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <Text style={{ color: t.text, fontSize: 13, fontWeight: '700' }}>{label}</Text>
          <Text style={{ color: col, fontSize: 13, fontWeight: '800' }}>{c.pts}/{c.max}</Text>
        </View>
        {c.value ? <Text style={{ fontSize: 12, color: t.accent, marginBottom: 6, fontWeight: '600' }}>{c.value}</Text> : null}
        <View style={{ height: 5, backgroundColor: t.border, borderRadius: 3, overflow: 'hidden', marginBottom: 6 }}>
          <View style={{ height: 5, backgroundColor: col, borderRadius: 3, width: `${pct2}%` as any }} />
        </View>
        {c.reason ? <Text style={{ color: t.textSub, fontSize: 12, lineHeight: 17 }}>{c.reason}</Text> : null}
      </View>
    );
  };

  const Dot = ({ text, color }: any) => (
    <View style={gs.dotRow}>
      <View style={[gs.dot, { backgroundColor: color + '25' }]}><Text style={{ color, fontSize: 10, fontWeight: '800' }}>·</Text></View>
      <Text style={{ flex: 1, fontSize: 14, lineHeight: 22, color: t.text }}>{text}</Text>
    </View>
  );

  const pa = r.profitability_analysis || {};
  const la = r.liquidity_analysis || {};
  const lv = r.leverage_analysis || {};
  const ea = r.efficiency_analysis || {};
  const cfa = r.cash_flow_analysis || {};
  const ha = r.horizontal_analysis || {};
  const thesis = r.investment_thesis || {};
  const sa = r.segment_analysis || {};
  const mc = r.management_commentary || {};
  const is = r.income_statement || {};
  const bs = r.balance_sheet || {};
  const cf = r.cash_flow_statement || {};

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <Animated.ScrollView style={{ opacity: fadeAnim }} showsVerticalScrollIndicator={false}>

        {/* Top bar */}
        <View style={[gs.topBar, { borderBottomColor: t.border }]}>
          <TouchableOpacity onPress={handleBack}><Text style={[gs.backText, { color: t.accent }]}>← Back</Text></TouchableOpacity>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text style={{ fontSize: 18 }}>📊</Text>
            <Text style={{ color: t.accent, fontSize: 17, fontWeight: '900', letterSpacing: -0.5 }}>FinSight</Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text style={{ fontSize: 14 }}>{dark ? '🌙' : '☀️'}</Text>
            <Switch value={dark} onValueChange={setDark} trackColor={{ false: '#CBD5E1', true: t.accent }} thumbColor="#fff" style={{ transform: [{ scale: 0.8 }] }} />
          </View>
        </View>

        <View style={{ paddingHorizontal: 16 }}>

          {/* Company header */}
          <View style={{ paddingTop: 20, paddingBottom: 16 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
              <Text style={{ fontSize: 26, fontWeight: '900', letterSpacing: -0.8, color: t.text }}>{r.company_name}</Text>
              {r.analyst_rating && (
                <View style={{ backgroundColor: ratingColor, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 5 }}>
                  <Text style={{ color: '#fff', fontSize: 13, fontWeight: '900' }}>{r.analyst_rating}</Text>
                </View>
              )}
            </View>
            <Text style={{ fontSize: 13, color: t.textSub }}>
              {[r.ticker, r.exchange, r.statement_type, r.period, r.unit].filter(Boolean).join(' · ')}
            </Text>
          </View>

          {/* Bloomberg headline */}
          {r.headline && (
            <View style={{ backgroundColor: t.accentBg, borderLeftWidth: 3, borderLeftColor: t.accent, borderRadius: 12, padding: 14, marginBottom: 14 }}>
              <Text style={{ fontSize: 14, fontWeight: '700', color: t.text, lineHeight: 21 }}>{r.headline}</Text>
            </View>
          )}

          {/* Health score card */}
          <View style={[gs.scoreCard, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '700', letterSpacing: 2, textTransform: 'uppercase', color: t.textSub, marginBottom: 10 }}>Financial Health Score</Text>
            <View style={{ flexDirection: 'row', alignItems: 'flex-end' }}>
              <Text style={{ fontSize: 82, fontWeight: '900', lineHeight: 90, letterSpacing: -4, color: sc }}>{r.health_score}</Text>
              <Text style={{ fontSize: 28, fontWeight: '600', color: t.textSub, marginBottom: 14 }}>/100</Text>
            </View>
            <View style={{ borderRadius: 24, paddingHorizontal: 22, paddingVertical: 7, backgroundColor: sc + '20', marginBottom: r.analyst_rating ? 10 : 0 }}>
              <Text style={{ fontSize: 16, fontWeight: '800', color: sc }}>{r.health_label}</Text>
            </View>
            {r.analyst_rating_rationale && (
              <Text style={{ fontSize: 12, color: t.textSub, marginTop: 12, textAlign: 'center', lineHeight: 18 }}>{r.analyst_rating_rationale}</Text>
            )}
            {bKeys.some(k => breakdown[k]) && (
              <View style={{ width: '100%', marginTop: 22 }}>
                <Text style={[gs.cardTitle, { color: t.text, marginBottom: 12 }]}>Score Breakdown</Text>
                {bKeys.map(k => <ScoreBar key={k} k={k} />)}
              </View>
            )}
          </View>

          {/* Executive Summary */}
          {r.executive_summary && (
            <Card title="📋 Executive Summary">
              <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.executive_summary}</Text>
            </Card>
          )}

          {/* Investment Thesis */}
          {(thesis.bull_case || thesis.bear_case || thesis.key_monitorables?.length) && (
            <Card title="⚖️ Investment Thesis">
              {thesis.bull_case && (
                <View style={{ marginBottom: 14 }}>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#22c55e', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>🐂 Bull Case</Text>
                  <Text style={{ fontSize: 13, lineHeight: 21, color: t.text }}>{thesis.bull_case}</Text>
                </View>
              )}
              {thesis.bear_case && (
                <View style={{ marginBottom: 14 }}>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: '#ef4444', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>🐻 Bear Case</Text>
                  <Text style={{ fontSize: 13, lineHeight: 21, color: t.text }}>{thesis.bear_case}</Text>
                </View>
              )}
              {thesis.key_monitorables?.length > 0 && (
                <View>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: t.textSub, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Key Monitorables</Text>
                  {thesis.key_monitorables.map((item: string, i: number) => <Dot key={i} text={item} color={t.accent} />)}
                </View>
              )}
            </Card>
          )}

          {/* Investor Verdict */}
          {r.investor_verdict && (
            <Card title="💡 Investor Verdict" leftBorder={t.accent}>
              <View style={{ backgroundColor: t.accentBg, borderRadius: 12, padding: 16 }}>
                <Text style={{ fontSize: 14, lineHeight: 23, color: t.text }}>{r.investor_verdict}</Text>
              </View>
            </Card>
          )}

          {/* Key Metrics */}
          {r.key_metrics?.filter((m: any) => m.current && m.current !== 'N/A' && m.current !== '').length > 0 && (
            <Card title="📊 Key Metrics">
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: t.border, marginBottom: 4 }}>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Metric</Text>
                <Text style={{ fontSize: 10, fontWeight: '700', color: t.textSub, textTransform: 'uppercase', letterSpacing: 0.5 }}>Now · Before · Δ</Text>
              </View>
              {r.key_metrics.map((m: any, i: number) => <MetricRow key={i} m={m} />)}
            </Card>
          )}

          {/* Income Statement */}
          {curr(is.revenue) && (
            <Card title="📈 Income Statement">
              {[
                ['Revenue', is.revenue], ['Other Income', is.other_income], ['Total Income', is.total_income],
                ['COGS', is.cost_of_goods_sold], ['Gross Profit', is.gross_profit], ['Employee Costs', is.employee_costs],
                ['EBITDA', is.ebitda], ['Depreciation', is.depreciation], ['EBIT', is.ebit],
                ['Finance Cost', is.finance_cost], ['PBT', is.pbt], ['Tax', is.tax_expense],
                ['PAT', is.pat], ['EPS Basic', is.eps_basic], ['EPS Diluted', is.eps_diluted],
              ].map(([label, obj]: any, i) => <ISRow key={i} label={label} obj={obj} />)}
            </Card>
          )}

          {/* Balance Sheet */}
          {curr(bs.total_assets) && (
            <Card title="🏦 Balance Sheet">
              {[
                ['Total Assets', bs.total_assets], ['Current Assets', bs.current_assets],
                ['Inventories', bs.inventories], ['Trade Receivables', bs.trade_receivables],
                ['Cash & Equivalents', bs.cash_equivalents], ['Total Equity', bs.total_equity],
                ['Total Borrowings', bs.total_borrowings], ['LT Borrowings', bs.long_term_borrowings],
                ['ST Borrowings', bs.short_term_borrowings], ['Trade Payables', bs.trade_payables],
                ['Current Liabilities', bs.current_liabilities],
              ].map(([label, obj]: any, i) => <ISRow key={i} label={label} obj={obj} />)}
            </Card>
          )}

          {/* Cash Flow */}
          {curr(cf.operating_cash_flow) && (
            <Card title="💰 Cash Flow Statement">
              {[
                ['Operating CF', cf.operating_cash_flow], ['Investing CF', cf.investing_cash_flow],
                ['Financing CF', cf.financing_cash_flow], ['Capex', cf.capex], ['Free Cash Flow', cf.free_cash_flow],
              ].map(([label, obj]: any, i) => <ISRow key={i} label={label} obj={obj} />)}
            </Card>
          )}

          {/* Profitability */}
          {pa.commentary && (
            <Card title="💹 Profitability Analysis">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Gross Margin" value={pa.gross_margin_pct ? pa.gross_margin_pct + '%' : null} color="#22c55e" />
                <Stat label="EBITDA Margin" value={pa.ebitda_margin_pct ? pa.ebitda_margin_pct + '%' : null} color="#4F8AFF" />
                <Stat label="Net Margin" value={pa.net_profit_margin_pct ? pa.net_profit_margin_pct + '%' : null} color="#f59e0b" />
                <Stat label="ROE" value={pa.roe_pct ? pa.roe_pct + '%' : null} color="#22c55e" />
                <Stat label="ROA" value={pa.roa_pct ? pa.roa_pct + '%' : null} color="#22c55e" />
                <Stat label="ROIC" value={pa.roic_pct ? pa.roic_pct + '%' : null} color="#22c55e" />
                <Stat label="ROCE" value={pa.roce_pct ? pa.roce_pct + '%' : null} color="#22c55e" />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{pa.commentary}</Text>
            </Card>
          )}

          {/* Leverage */}
          {lv.commentary && (
            <Card title="🏗️ Leverage & Debt">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="D/E Ratio" value={lv.debt_to_equity} color="#f59e0b" />
                <Stat label="Net Debt/EBITDA" value={lv.net_debt_to_ebitda} color="#f59e0b" />
                <Stat label="Interest Cover" value={lv.interest_coverage_ratio ? lv.interest_coverage_ratio + 'x' : null} color="#22c55e" />
                <Stat label="Net Debt" value={lv.net_debt} />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{lv.commentary}</Text>
            </Card>
          )}

          {/* Liquidity */}
          {la.commentary && (
            <Card title="💧 Liquidity">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Current Ratio" value={la.current_ratio} color="#4F8AFF" />
                <Stat label="Quick Ratio" value={la.quick_ratio} color="#4F8AFF" />
                <Stat label="Cash Ratio" value={la.cash_ratio} color="#4F8AFF" />
                <Stat label="NWC" value={la.net_working_capital} />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{la.commentary}</Text>
            </Card>
          )}

          {/* Cash Flow Analysis */}
          {cfa.commentary && (
            <Card title="🌊 Cash Flow Quality">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="OCF/PAT" value={cfa.ocf_to_pat_ratio ? cfa.ocf_to_pat_ratio + 'x' : null} />
                <Stat label="FCF Margin" value={cfa.fcf_margin_pct ? cfa.fcf_margin_pct + '%' : null} />
                {cfa.cash_quality && (
                  <View style={[gs.statBox, { backgroundColor: cfa.cash_quality === 'Strong' ? '#22c55e20' : '#f59e0b20', borderColor: t.border }]}>
                    <Text style={{ fontSize: 14, fontWeight: '800', color: cfa.cash_quality === 'Strong' ? '#22c55e' : '#f59e0b' }}>{cfa.cash_quality}</Text>
                    <Text style={{ fontSize: 10, color: t.textSub, marginTop: 4, fontWeight: '600' }}>Cash Quality</Text>
                  </View>
                )}
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{cfa.commentary}</Text>
            </Card>
          )}

          {/* Efficiency */}
          {ea.commentary && (
            <Card title="⚙️ Efficiency Analysis">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Inventory Days" value={ea.inventory_turnover_days} />
                <Stat label="Receivable Days" value={ea.receivables_turnover_days} />
                <Stat label="Payable Days" value={ea.payables_turnover_days} />
                <Stat label="CCC Days" value={ea.cash_conversion_cycle_days} />
                <Stat label="Asset Turnover" value={ea.asset_turnover ? ea.asset_turnover + 'x' : null} />
              </View>
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{ea.commentary}</Text>
            </Card>
          )}

          {/* Segments */}
          {sa.segments?.filter((s: any) => s.name).length > 0 && (
            <Card title="🏢 Segment Analysis">
              {sa.segments.filter((s: any) => s.name).map((s: any, i: number) => (
                <View key={i} style={[gs.segCard, { backgroundColor: t.cardAlt, borderColor: t.border }]}>
                  <Text style={{ color: t.text, fontSize: 14, fontWeight: '700', marginBottom: 8 }}>{s.name}</Text>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                    {s.revenue && <View style={{ backgroundColor: t.accentBg, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: t.accent, fontSize: 11, fontWeight: '700' }}>Rev: {s.revenue}</Text></View>}
                    {s.revenue_pct_total && <View style={{ backgroundColor: '#f59e0b20', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: '#f59e0b', fontSize: 11, fontWeight: '700' }}>{s.revenue_pct_total} of total</Text></View>}
                    {s.ebit_margin && <View style={{ backgroundColor: '#22c55e20', borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 }}><Text style={{ color: '#22c55e', fontSize: 11, fontWeight: '700' }}>Margin: {s.ebit_margin}</Text></View>}
                  </View>
                </View>
              ))}
              {sa.commentary && <Text style={{ fontSize: 13, color: t.textSub, lineHeight: 20 }}>{sa.commentary}</Text>}
            </Card>
          )}

          {/* Horizontal Analysis */}
          {ha.notable_trends?.length > 0 && (
            <Card title="📉 Trend Analysis">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                <Stat label="Revenue Growth" value={ha.revenue_growth_yoy_pct ? ha.revenue_growth_yoy_pct + '%' : null} color="#22c55e" />
                <Stat label="PAT Growth" value={ha.pat_growth_yoy_pct ? ha.pat_growth_yoy_pct + '%' : null} color="#22c55e" />
                <Stat label="EPS Growth" value={ha.eps_growth_yoy_pct ? ha.eps_growth_yoy_pct + '%' : null} color="#22c55e" />
              </View>
              {ha.notable_trends.map((trend: string, i: number) => <Dot key={i} text={trend} color={t.accent} />)}
            </Card>
          )}

          {/* Management Commentary */}
          {(mc.guidance || mc.key_developments?.length) && (
            <Card title="🎙️ Management Commentary">
              {mc.guidance && (
                <View style={{ backgroundColor: t.accentBg, borderLeftWidth: 3, borderLeftColor: t.accent, borderRadius: 10, padding: 14, marginBottom: 14 }}>
                  <Text style={{ fontSize: 11, fontWeight: '800', color: t.accent, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Guidance</Text>
                  <Text style={{ fontSize: 13, lineHeight: 20, color: t.text }}>{mc.guidance}</Text>
                </View>
              )}
              {mc.key_developments?.map((d: string, i: number) => <Dot key={i} text={d} color={t.accent} />)}
            </Card>
          )}

          {/* Strengths / Risks / Watch */}
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

          {/* Peer Context */}
          {r.peer_context && (
            <Card title="🔗 Peer Context">
              <Text style={{ fontSize: 14, lineHeight: 22, color: t.text }}>{r.peer_context}</Text>
            </Card>
          )}

          {/* Save & Share */}
          <View style={[gs.sharePanel, { backgroundColor: t.card, borderColor: t.border }]}>
            <Text style={{ fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', color: t.textSub, textAlign: 'center', marginBottom: 18 }}>SAVE & SHARE</Text>
            <TouchableOpacity style={[gs.pdfBtn, { backgroundColor: t.accent, opacity: downloading ? 0.7 : 1 }]} onPress={handleDownloadPDF} disabled={downloading}>
              {downloading ? <ActivityIndicator color="#fff" /> : <>
                <Text style={{ fontSize: 22 }}>⬇️</Text>
                <View>
                  <Text style={{ color: '#fff', fontSize: 16, fontWeight: '800' }}>Download Full PDF Report</Text>
                  <Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, marginTop: 2 }}>Institutional-grade · {dark ? 'Dark' : 'Light'} theme</Text>
                </View>
              </>}
            </TouchableOpacity>
            <View style={{ flexDirection: 'row', gap: 10, marginBottom: 12 }}>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: '#25D366' }]} onPress={handleWhatsAppShare}><Text style={{ fontSize: 18, marginBottom: 3 }}>💬</Text><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>WhatsApp</Text></TouchableOpacity>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: '#000' }]} onPress={handleTwitterShare}><Text style={{ fontSize: 18, marginBottom: 3 }}>𝕏</Text><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Twitter</Text></TouchableOpacity>
              <TouchableOpacity style={[gs.shareBtn, { backgroundColor: t.accent }]} onPress={handleGenericShare}><Text style={{ fontSize: 18, marginBottom: 3 }}>📤</Text><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>Share</Text></TouchableOpacity>
            </View>
            <TouchableOpacity style={[gs.copyBtn, { borderColor: copied ? '#22c55e' : t.accent, backgroundColor: copied ? '#22c55e15' : t.accentBg }]} onPress={handleCopyLink}>
              <Text style={{ color: copied ? '#22c55e' : t.accent, fontSize: 15, fontWeight: '700' }}>{copied ? '✅ Link Copied!' : '🔗 Copy Shareable Link'}</Text>
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
  statBox:    { borderRadius: 14, padding: 14, minWidth: '30%', flex: 1, alignItems: 'center', borderWidth: 1 },
  dotRow:     { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 12 },
  dot:        { width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', marginRight: 12, marginTop: 1, flexShrink: 0 },
  segCard:    { borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1 },
  sharePanel: { borderRadius: 22, padding: 20, marginBottom: 14, borderWidth: 1 },
  pdfBtn:     { borderRadius: 16, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 14 },
  shareBtn:   { flex: 1, borderRadius: 14, paddingVertical: 14, alignItems: 'center' },
  copyBtn:    { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1.5 },
  backBtn:    { borderRadius: 14, padding: 14, alignItems: 'center', borderWidth: 1, marginBottom: 4 },
});
