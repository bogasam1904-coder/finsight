import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView,
  Alert, RefreshControl, StatusBar
} from 'react-native';
import { useRouter, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || 'https://loyal-integrity-production-2b54.up.railway.app';

export default function HistoryTab() {
  const router = useRouter();
  const [analyses, setAnalyses] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [isGuest, setIsGuest] = useState(false);

  useFocusEffect(useCallback(() => { load(); }, []));

  const load = async () => {
    const token = await AsyncStorage.getItem('token');
    if (!token) { setIsGuest(true); setLoading(false); setRefreshing(false); return; }
    setIsGuest(false);
    try {
      const res = await fetch(`${BACKEND}/api/analyses`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) { const d = await res.json(); if (Array.isArray(d)) setAnalyses(d); }
    } catch { }
    finally { setLoading(false); setRefreshing(false); }
  };

  const handleDelete = (id: string) => {
    Alert.alert('Delete', 'Remove this analysis?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        const token = await AsyncStorage.getItem('token');
        await fetch(`${BACKEND}/api/analyses/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
        setAnalyses(prev => prev.filter(a => a.analysis_id !== id));
      }}
    ]);
  };

  const scoreColor = (s: number) => s >= 80 ? '#22c55e' : s >= 60 ? '#f59e0b' : '#ef4444';
  const timeAgo = (d: string) => {
    const diff = Date.now() - new Date(d).getTime();
    const h = Math.floor(diff / 3600000), days = Math.floor(diff / 86400000);
    if (h < 1) return 'Just now'; if (h < 24) return `${h}h ago`; return `${days}d ago`;
  };

  return (
    <View style={hs.root}>
      <StatusBar barStyle="light-content" />
      <View style={hs.bg}><View style={[hs.blob, { width: 300, height: 300, backgroundColor: 'rgba(79,138,255,0.08)', top: -80, right: -80 }]} /></View>
      <ScrollView showsVerticalScrollIndicator={false} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor="#4F8AFF" />}>
        <View style={hs.header}>
          <Text style={hs.title}>History</Text>
          <Text style={hs.subtitle}>{analyses.length} analyses</Text>
        </View>

        {isGuest && (
          <View style={hs.guestMsg}>
            <Text style={hs.guestMsgTitle}>📭 No history for guests</Text>
            <Text style={hs.guestMsgSub}>Create a free account to save and revisit all your analyses</Text>
            <View style={hs.guestBtns}>
              <TouchableOpacity style={hs.guestBtn} onPress={() => router.push('/register')}>
                <Text style={hs.guestBtnText}>Create Free Account</Text>
              </TouchableOpacity>
              <TouchableOpacity style={hs.guestBtnSecondary} onPress={() => router.push('/login')}>
                <Text style={hs.guestBtnSecondaryText}>Sign In</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {!isGuest && !loading && analyses.length === 0 && (
          <View style={hs.empty}>
            <Text style={{ fontSize: 56, marginBottom: 16 }}>📭</Text>
            <Text style={hs.emptyTitle}>No analyses yet</Text>
            <Text style={hs.emptySub}>Upload your first financial document to get started</Text>
            <TouchableOpacity style={hs.emptyBtn} onPress={() => router.push('/(tabs)')}>
              <Text style={hs.emptyBtnText}>Upload Document</Text>
            </TouchableOpacity>
          </View>
        )}

        {analyses.length > 0 && (
          <View style={hs.list}>
            {analyses.map((a, i) => {
              const sc = a.result?.health_score;
              const col = sc ? scoreColor(sc) : '#6B82A8';
              const done = a.status === 'completed';
              const failed = a.status === 'failed';
              return (
                <TouchableOpacity key={i} style={hs.card}
                  onPress={() => done && router.push(`/analysis/${a.analysis_id}`)}
                  onLongPress={() => handleDelete(a.analysis_id)}
                >
                  <View style={hs.cardTop}>
                    <View style={hs.cardLeft}>
                      <View style={[hs.dot, { backgroundColor: done ? '#22c55e' : failed ? '#ef4444' : '#f59e0b' }]} />
                      <View style={{ flex: 1 }}>
                        <Text style={hs.cardCompany} numberOfLines={1}>{a.result?.company_name || a.filename}</Text>
                        <Text style={hs.cardMeta}>{[a.result?.statement_type, a.result?.period, timeAgo(a.created_at)].filter(Boolean).join(' · ')}</Text>
                      </View>
                    </View>
                    {sc ? (
                      <View style={[hs.scorePill, { backgroundColor: col + '1A' }]}>
                        <Text style={[hs.scoreNum, { color: col }]}>{sc}</Text>
                        <Text style={[hs.scoreDenom, { color: col }]}>/100</Text>
                      </View>
                    ) : (
                      <View style={[hs.statusPill, { backgroundColor: failed ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)' }]}>
                        <Text style={{ color: failed ? '#ef4444' : '#f59e0b', fontSize: 11, fontWeight: '700' }}>{failed ? 'Failed' : 'Processing'}</Text>
                      </View>
                    )}
                  </View>
                  {done && a.result?.investor_verdict && <Text style={hs.verdict} numberOfLines={2}>{a.result.investor_verdict}</Text>}
                  {failed && a.message && <Text style={hs.errorMsg} numberOfLines={1}>{a.message}</Text>}
                  <View style={hs.footer}>
                    <View style={hs.tags}>
                      {a.result?.health_label && <View style={hs.tag}><Text style={hs.tagText}>{a.result.health_label}</Text></View>}
                      {a.result?.currency && <View style={hs.tag}><Text style={hs.tagText}>{a.result.currency}</Text></View>}
                    </View>
                    <Text style={hs.holdHint}>Hold to delete</Text>
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>
        )}
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const hs = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#060B18' },
  bg: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  blob: { position: 'absolute', borderRadius: 999 },
  header: { paddingHorizontal: 22, paddingTop: 58, paddingBottom: 20 },
  title: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: -0.8, marginBottom: 4 },
  subtitle: { color: 'rgba(255,255,255,0.3)', fontSize: 14 },
  guestMsg: { marginHorizontal: 20, backgroundColor: '#0D1426', borderRadius: 22, padding: 28, alignItems: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' },
  guestMsgTitle: { color: '#fff', fontSize: 18, fontWeight: '800', marginBottom: 8 },
  guestMsgSub: { color: 'rgba(255,255,255,0.35)', fontSize: 13, textAlign: 'center', marginBottom: 22 },
  guestBtns: { flexDirection: 'row', gap: 10 },
  guestBtn: { backgroundColor: '#4F8AFF', borderRadius: 14, paddingVertical: 12, paddingHorizontal: 20 },
  guestBtnText: { color: '#fff', fontSize: 14, fontWeight: '700' },
  guestBtnSecondary: { backgroundColor: 'rgba(255,255,255,0.07)', borderRadius: 14, paddingVertical: 12, paddingHorizontal: 20, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)' },
  guestBtnSecondaryText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  empty: { alignItems: 'center', paddingTop: 80, paddingHorizontal: 40 },
  emptyTitle: { color: '#fff', fontSize: 20, fontWeight: '800', marginBottom: 8 },
  emptySub: { color: 'rgba(255,255,255,0.3)', fontSize: 13, textAlign: 'center', marginBottom: 24 },
  emptyBtn: { backgroundColor: '#4F8AFF', borderRadius: 14, paddingVertical: 14, paddingHorizontal: 26 },
  emptyBtnText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  list: { paddingHorizontal: 20 },
  card: { backgroundColor: '#0D1426', borderRadius: 20, padding: 18, marginBottom: 12, borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)' },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 },
  cardLeft: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, flex: 1, paddingRight: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 5, flexShrink: 0 },
  cardCompany: { color: '#fff', fontSize: 15, fontWeight: '700', marginBottom: 3 },
  cardMeta: { color: 'rgba(255,255,255,0.3)', fontSize: 12 },
  scorePill: { borderRadius: 12, paddingHorizontal: 10, paddingVertical: 7, flexDirection: 'row', alignItems: 'baseline', gap: 1 },
  scoreNum: { fontSize: 20, fontWeight: '900' },
  scoreDenom: { fontSize: 11, fontWeight: '600' },
  statusPill: { borderRadius: 8, paddingHorizontal: 10, paddingVertical: 7 },
  verdict: { color: 'rgba(255,255,255,0.38)', fontSize: 12, lineHeight: 18, marginBottom: 10 },
  errorMsg: { color: '#ef4444', fontSize: 11, marginBottom: 10, fontStyle: 'italic' },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  tags: { flexDirection: 'row', gap: 6 },
  tag: { backgroundColor: 'rgba(79,138,255,0.12)', borderRadius: 7, paddingHorizontal: 8, paddingVertical: 4 },
  tagText: { color: '#4F8AFF', fontSize: 10, fontWeight: '700' },
  holdHint: { color: 'rgba(255,255,255,0.12)', fontSize: 10 },
});
