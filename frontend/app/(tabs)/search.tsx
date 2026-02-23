import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ScrollView, ActivityIndicator, StatusBar, Animated,
  Alert, Dimensions
} from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width } = Dimensions.get('window');
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

const SECTOR_COLORS: Record<string, string> = {
  'IT': '#4F8AFF', 'Banking': '#f59e0b', 'FMCG': '#22c55e',
  'Pharma': '#a78bfa', 'Auto': '#f97316', 'Energy': '#ef4444',
  'Metals': '#94a3b8', 'Finance': '#06b6d4', 'Telecom': '#ec4899',
  'Power': '#eab308', 'Infrastructure': '#84cc16', 'Cement': '#a3a3a3',
  'Chemicals': '#10b981', 'Consumer': '#f472b6', 'Electricals': '#fbbf24',
  'Logistics': '#8b5cf6', 'Diversified': '#6366f1', 'Insurance': '#38bdf8',
  'Healthcare': '#34d399', 'Retail': '#fb923c', 'E-Commerce': '#a78bfa',
  'Fintech': '#4F8AFF', 'Services': '#64748b',
};

const TYPE_CONFIG: Record<string, { color: string; icon: string }> = {
  'Annual Report':    { color: '#4F8AFF', icon: '📗' },
  'Q1 Results':       { color: '#22c55e', icon: '📊' },
  'Q2 Results':       { color: '#22c55e', icon: '📊' },
  'Q3 Results':       { color: '#22c55e', icon: '📊' },
  'Q4 Results':       { color: '#22c55e', icon: '📊' },
  'Half-Year Results':{ color: '#f59e0b', icon: '📈' },
  'Financial Results':{ color: '#f59e0b', icon: '📈' },
  'Filing':           { color: '#94a3b8', icon: '📄' },
};

function getTypeConfig(type: string) {
  return TYPE_CONFIG[type] || { color: '#4F8AFF', icon: '📄' };
}

export default function SearchTab() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [companies, setCompanies] = useState<any[]>([]);
  const [popular, setPopular] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState<any>(null);
  const [filings, setFilings] = useState<any[]>([]);
  const [loadingFilings, setLoadingFilings] = useState(false);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const debounceRef = useRef<any>(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const filingsFadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 600, useNativeDriver: true }).start();
    loadPopular();
  }, []);

  const loadPopular = async () => {
    try {
      const res = await fetch(`${BACKEND}/api/nse/popular`);
      const data = await res.json();
      if (data.results) setPopular(data.results);
    } catch { }
  };

  const handleQueryChange = (text: string) => {
    setQuery(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text.trim()) { setCompanies([]); setNotFound(false); setSelectedCompany(null); setFilings([]); return; }
    debounceRef.current = setTimeout(() => searchCompanies(text), 300);
  };

  const searchCompanies = async (q: string) => {
    setSearching(true); setNotFound(false);
    try {
      const res = await fetch(`${BACKEND}/api/nse/search?q=${encodeURIComponent(q.trim())}`);
      const data = await res.json();
      const list = data.results || [];
      setCompanies(list);
      setNotFound(list.length === 0);
    } catch { setCompanies([]); setNotFound(true); }
    finally { setSearching(false); }
  };

  const selectCompany = async (company: any) => {
    if (selectedCompany?.symbol === company.symbol) {
      setSelectedCompany(null); setFilings([]); return;
    }
    setSelectedCompany(company);
    setFilings([]);
    setLoadingFilings(true);
    filingsFadeAnim.setValue(0);
    
    try {
      const res = await fetch(`${BACKEND}/api/filings/${company.symbol}`);
      if (!res.ok) throw new Error('Failed to fetch filings');
      const data = await res.json();
      setFilings(data.filings || []);
      Animated.timing(filingsFadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
    } catch (e) {
      setFilings([]);
      Alert.alert('Could not fetch filings', 'NSE/BSE may be temporarily unavailable. Try again shortly.');
    } finally { setLoadingFilings(false); }
  };

  const analyzeFromUrl = async (filing: any) => {
    const key = `${filing.source}_${filing.title.substring(0,20)}`;
    setAnalyzingId(key);
    
    try {
      const token = await AsyncStorage.getItem('token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      
      const res = await fetch(`${BACKEND}/api/analyze-from-url`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          pdf_url: filing.pdf_url,
          filename: `${selectedCompany?.symbol}_${filing.type.replace(/\s/g,'_')}.pdf`,
          source: filing.source.toLowerCase(),
        }),
      });
      
      const text = await res.text();
      let data: any;
      try { data = JSON.parse(text); } catch { throw new Error('Server error'); }
      
      if (data.status === 'completed' && data.analysis_id) {
        router.push(`/analysis/${data.analysis_id}`);
      } else {
        throw new Error(data.message || 'Analysis failed');
      }
    } catch (e: any) {
      Alert.alert(
        'Analysis Failed',
        e.message || 'Could not analyse this filing. The PDF may be password-protected or inaccessible.',
        [{ text: 'OK' }]
      );
    } finally { setAnalyzingId(null); }
  };

  const displayCompanies = query.trim() ? companies : popular;
  const sc = (sector: string) => SECTOR_COLORS[sector] || '#4F8AFF';

  return (
    <View style={s.root}>
      <StatusBar barStyle="light-content" />
      <View style={s.bgBlobs}>
        <View style={[s.blob, { width: 280, height: 280, backgroundColor: 'rgba(79,138,255,0.1)', top: -80, right: -80 }]} />
        <View style={[s.blob, { width: 200, height: 200, backgroundColor: 'rgba(34,197,94,0.06)', bottom: 100, left: -60 }]} />
      </View>

      <Animated.View style={[s.container, { opacity: fadeAnim }]}>
        {/* Header */}
        <View style={s.header}>
          <Text style={s.title}>Search & Analyse</Text>
          <Text style={s.subtitle}>Find any NSE-listed company and analyse their filings directly</Text>
        </View>

        {/* Search bar */}
        <View style={s.searchRow}>
          <View style={s.searchBar}>
            <Text style={s.searchIcon}>🔍</Text>
            <TextInput
              style={s.searchInput}
              placeholder="Search company or symbol..."
              placeholderTextColor="rgba(255,255,255,0.25)"
              value={query}
              onChangeText={handleQueryChange}
              autoCapitalize="characters"
              autoCorrect={false}
            />
            {searching && <ActivityIndicator size="small" color="#4F8AFF" style={{ marginRight: 4 }} />}
            {query.length > 0 && !searching && (
              <TouchableOpacity onPress={() => { setQuery(''); setCompanies([]); setSelectedCompany(null); setFilings([]); setNotFound(false); }}>
                <Text style={s.clearBtn}>✕</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        <ScrollView showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

          {/* No results */}
          {notFound && (
            <View style={s.notFoundBox}>
              <Text style={s.notFoundEmoji}>🔍</Text>
              <Text style={s.notFoundTitle}>No results for "{query}"</Text>
              <Text style={s.notFoundSub}>Try the NSE symbol (e.g. RELIANCE, TCS, SBIN) or full company name</Text>
            </View>
          )}

          {/* Company list */}
          {displayCompanies.length > 0 && (
            <View style={s.section}>
              <Text style={s.sectionLabel}>
                {query.trim() ? `${companies.length} result${companies.length !== 1 ? 's' : ''}` : '🔥 Popular Companies'}
              </Text>

              {displayCompanies.map((company, i) => {
                const isSelected = selectedCompany?.symbol === company.symbol;
                const color = sc(company.sector);

                return (
                  <View key={i}>
                    {/* Company row */}
                    <TouchableOpacity
                      style={[s.companyRow, isSelected && { borderBottomLeftRadius: 0, borderBottomRightRadius: 0, borderBottomWidth: 0 }]}
                      onPress={() => selectCompany(company)}
                    >
                      <View style={[s.symbolBadge, { backgroundColor: color + '20' }]}>
                        <Text style={[s.symbolText, { color }]}>{company.symbol}</Text>
                      </View>
                      <View style={s.companyInfo}>
                        <Text style={s.companyName} numberOfLines={1}>{company.name}</Text>
                        <View style={[s.sectorPill, { backgroundColor: color + '18' }]}>
                          <Text style={[s.sectorText, { color }]}>{company.sector}</Text>
                        </View>
                      </View>
                      <View style={s.rowRight}>
                        <Text style={[s.chevron, { color: isSelected ? '#4F8AFF' : 'rgba(255,255,255,0.2)' }]}>
                          {isSelected ? '▲' : '▼'}
                        </Text>
                      </View>
                    </TouchableOpacity>

                    {/* Filings expanded panel */}
                    {isSelected && (
                      <View style={s.filingsPanel}>
                        {loadingFilings ? (
                          <View style={s.filingsLoading}>
                            <ActivityIndicator color="#4F8AFF" />
                            <Text style={s.filingsLoadingText}>
                              Fetching latest filings from NSE & BSE...
                            </Text>
                          </View>
                        ) : filings.length === 0 ? (
                          <View style={s.filingsEmpty}>
                            <Text style={s.filingsEmptyIcon}>📭</Text>
                            <Text style={s.filingsEmptyTitle}>No filings found</Text>
                            <Text style={s.filingsEmptyText}>
                              NSE/BSE didn't return filings for {company.symbol} right now. Try again or upload a PDF manually.
                            </Text>
                          </View>
                        ) : (
                          <Animated.View style={{ opacity: filingsFadeAnim }}>
                            <Text style={s.filingsHeader}>
                              📂 {filings.length} filings found — tap to analyse instantly
                            </Text>
                            {filings.map((filing, fi) => {
                              const typeConf = getTypeConfig(filing.type);
                              const isAnalyzing = analyzingId === `${filing.source}_${filing.title.substring(0,20)}`;
                              return (
                                <View key={fi} style={s.filingCard}>
                                  <View style={s.filingCardLeft}>
                                    {/* Type badge */}
                                    <View style={[s.typeBadge, { backgroundColor: typeConf.color + '20' }]}>
                                      <Text style={s.typeBadgeIcon}>{typeConf.icon}</Text>
                                      <Text style={[s.typeBadgeText, { color: typeConf.color }]}>{filing.type}</Text>
                                    </View>
                                    {/* Title */}
                                    <Text style={s.filingTitle} numberOfLines={2}>{filing.title}</Text>
                                    {/* Meta */}
                                    <View style={s.filingMeta}>
                                      <View style={[s.sourceTag, { backgroundColor: filing.source === 'BSE' ? 'rgba(178,34,34,0.15)' : 'rgba(0,82,255,0.15)' }]}>
                                        <Text style={[s.sourceTagText, { color: filing.source === 'BSE' ? '#ff6b6b' : '#4F8AFF' }]}>{filing.source}</Text>
                                      </View>
                                      {filing.date ? <Text style={s.filingDate}>{filing.date}</Text> : null}
                                    </View>
                                  </View>
                                  {/* Analyse button */}
                                  <TouchableOpacity
                                    style={[s.analyzeBtn, isAnalyzing && s.analyzeBtnLoading]}
                                    onPress={() => analyzeFromUrl(filing)}
                                    disabled={isAnalyzing || analyzingId !== null}
                                  >
                                    {isAnalyzing ? (
                                      <ActivityIndicator size="small" color="#fff" />
                                    ) : (
                                      <>
                                        <Text style={s.analyzeBtnIcon}>⚡</Text>
                                        <Text style={s.analyzeBtnText}>Analyse</Text>
                                      </>
                                    )}
                                  </TouchableOpacity>
                                </View>
                              );
                            })}
                            <Text style={s.filingsTip}>
                              💡 Tap Analyse to fetch and analyse the PDF directly — no download needed
                            </Text>
                          </Animated.View>
                        )}
                      </View>
                    )}
                  </View>
                );
              })}
            </View>
          )}

          {/* Empty state when no query and popular not loaded */}
          {!query.trim() && popular.length === 0 && (
            <View style={s.emptyHero}>
              <Text style={s.emptyHeroEmoji}>🔍</Text>
              <Text style={s.emptyHeroTitle}>Search any NSE company</Text>
              <Text style={s.emptyHeroSub}>
                Type a company name or NSE symbol above{'\n'}
                Get their annual reports & quarterly results{'\n'}
                Analyse directly — no download needed
              </Text>
              <View style={s.exampleChips}>
                {['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'SBIN'].map(sym => (
                  <TouchableOpacity key={sym} style={s.chip} onPress={() => { setQuery(sym); handleQueryChange(sym); }}>
                    <Text style={s.chipText}>{sym}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          )}

          {/* How it works */}
          {!query.trim() && popular.length > 0 && (
            <View style={s.howItWorks}>
              <Text style={s.howTitle}>How It Works</Text>
              {[
                { icon: '🔍', step: 'Search', desc: 'Type any company name or symbol' },
                { icon: '📂', step: 'Browse', desc: 'See latest annual reports & results from NSE/BSE' },
                { icon: '⚡', step: 'Analyse', desc: 'Tap Analyse — AI fetches & analyses the PDF for you' },
                { icon: '📊', step: 'Results', desc: 'Get full analysis with score, metrics & verdict' },
              ].map((h, i) => (
                <View key={i} style={s.howStep}>
                  <View style={s.howStepIcon}><Text style={{ fontSize: 20 }}>{h.icon}</Text></View>
                  <View style={s.howStepInfo}>
                    <Text style={s.howStepTitle}>{h.step}</Text>
                    <Text style={s.howStepDesc}>{h.desc}</Text>
                  </View>
                </View>
              ))}
            </View>
          )}

          <View style={{ height: 100 }} />
        </ScrollView>
      </Animated.View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#060B18' },
  bgBlobs: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, overflow: 'hidden' },
  blob: { position: 'absolute', borderRadius: 999 },
  container: { flex: 1 },
  header: { paddingHorizontal: 22, paddingTop: 58, paddingBottom: 12 },
  title: { color: '#fff', fontSize: 28, fontWeight: '900', letterSpacing: -0.8 },
  subtitle: { color: 'rgba(255,255,255,0.32)', fontSize: 13, marginTop: 4, lineHeight: 20 },
  searchRow: { paddingHorizontal: 20, marginBottom: 8 },
  searchBar: { backgroundColor: '#0D1426', borderRadius: 16, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 13, borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)' },
  searchIcon: { fontSize: 15, marginRight: 10 },
  searchInput: { flex: 1, color: '#fff', fontSize: 15, padding: 0 },
  clearBtn: { color: 'rgba(255,255,255,0.3)', fontSize: 16, paddingLeft: 8 },
  notFoundBox: { alignItems: 'center', paddingVertical: 48, paddingHorizontal: 32 },
  notFoundEmoji: { fontSize: 44, marginBottom: 14 },
  notFoundTitle: { color: '#fff', fontSize: 17, fontWeight: '700', marginBottom: 8 },
  notFoundSub: { color: 'rgba(255,255,255,0.32)', fontSize: 13, textAlign: 'center', lineHeight: 20 },
  section: { paddingHorizontal: 20 },
  sectionLabel: { color: 'rgba(255,255,255,0.32)', fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1.2, marginBottom: 10, marginTop: 4 },
  companyRow: { backgroundColor: '#0D1426', borderRadius: 18, padding: 16, marginBottom: 2, flexDirection: 'row', alignItems: 'center', gap: 14, borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  symbolBadge: { borderRadius: 12, paddingHorizontal: 10, paddingVertical: 7, minWidth: 70, alignItems: 'center', flexShrink: 0 },
  symbolText: { fontSize: 12, fontWeight: '900', letterSpacing: 0.3 },
  companyInfo: { flex: 1 },
  companyName: { color: '#fff', fontSize: 14, fontWeight: '700', marginBottom: 5 },
  sectorPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3, alignSelf: 'flex-start' },
  sectorText: { fontSize: 10, fontWeight: '700' },
  rowRight: { flexShrink: 0 },
  chevron: { fontSize: 12, fontWeight: '800' },
  filingsPanel: { backgroundColor: '#0A1220', borderWidth: 1, borderTopWidth: 0, borderColor: 'rgba(79,138,255,0.2)', borderBottomLeftRadius: 18, borderBottomRightRadius: 18, padding: 16, marginBottom: 10 },
  filingsLoading: { alignItems: 'center', paddingVertical: 28, gap: 12 },
  filingsLoadingText: { color: 'rgba(255,255,255,0.35)', fontSize: 13 },
  filingsEmpty: { alignItems: 'center', paddingVertical: 24 },
  filingsEmptyIcon: { fontSize: 36, marginBottom: 10 },
  filingsEmptyTitle: { color: '#fff', fontSize: 15, fontWeight: '700', marginBottom: 6 },
  filingsEmptyText: { color: 'rgba(255,255,255,0.35)', fontSize: 12, textAlign: 'center', lineHeight: 18 },
  filingsHeader: { color: '#4F8AFF', fontSize: 12, fontWeight: '700', marginBottom: 12 },
  filingCard: { backgroundColor: '#0D1426', borderRadius: 14, padding: 14, marginBottom: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)', gap: 10 },
  filingCardLeft: { flex: 1 },
  typeBadge: { flexDirection: 'row', alignItems: 'center', gap: 5, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, alignSelf: 'flex-start', marginBottom: 6 },
  typeBadgeIcon: { fontSize: 12 },
  typeBadgeText: { fontSize: 10, fontWeight: '800' },
  filingTitle: { color: '#fff', fontSize: 13, fontWeight: '600', lineHeight: 18, marginBottom: 6 },
  filingMeta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sourceTag: { borderRadius: 5, paddingHorizontal: 6, paddingVertical: 2 },
  sourceTagText: { fontSize: 9, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.5 },
  filingDate: { color: 'rgba(255,255,255,0.25)', fontSize: 11 },
  analyzeBtn: { backgroundColor: '#4F8AFF', borderRadius: 12, paddingVertical: 10, paddingHorizontal: 14, alignItems: 'center', flexShrink: 0, minWidth: 78 },
  analyzeBtnLoading: { backgroundColor: '#2563EB', opacity: 0.8 },
  analyzeBtnIcon: { fontSize: 16, marginBottom: 2 },
  analyzeBtnText: { color: '#fff', fontSize: 11, fontWeight: '800' },
  filingsTip: { color: 'rgba(255,255,255,0.2)', fontSize: 11, textAlign: 'center', marginTop: 4, fontStyle: 'italic' },
  emptyHero: { alignItems: 'center', paddingTop: 60, paddingHorizontal: 32 },
  emptyHeroEmoji: { fontSize: 64, marginBottom: 20 },
  emptyHeroTitle: { color: '#fff', fontSize: 22, fontWeight: '900', marginBottom: 12, letterSpacing: -0.5 },
  emptyHeroSub: { color: 'rgba(255,255,255,0.35)', fontSize: 14, textAlign: 'center', lineHeight: 24, marginBottom: 28 },
  exampleChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center' },
  chip: { backgroundColor: 'rgba(79,138,255,0.15)', borderRadius: 20, paddingHorizontal: 16, paddingVertical: 8, borderWidth: 1, borderColor: 'rgba(79,138,255,0.25)' },
  chipText: { color: '#4F8AFF', fontSize: 13, fontWeight: '700' },
  howItWorks: { marginHorizontal: 20, backgroundColor: '#0D1426', borderRadius: 20, padding: 20, marginTop: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  howTitle: { color: '#fff', fontSize: 15, fontWeight: '800', marginBottom: 16 },
  howStep: { flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 14 },
  howStepIcon: { width: 42, height: 42, borderRadius: 12, backgroundColor: 'rgba(79,138,255,0.1)', alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
  howStepInfo: { flex: 1 },
  howStepTitle: { color: '#fff', fontSize: 14, fontWeight: '700', marginBottom: 2 },
  howStepDesc: { color: 'rgba(255,255,255,0.35)', fontSize: 12, lineHeight: 18 },
});
