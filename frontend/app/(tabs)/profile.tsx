import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Alert, StatusBar } from 'react-native';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiFetch } from '../../src/api';

export default function ProfileTab() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [stats, setStats] = useState({ total: 0, completed: 0 });

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    const u = await AsyncStorage.getItem('user');
    if (u) setUser(JSON.parse(u));
    try {
      const res = await apiFetch('/analyses');
      const data = await res.json();
      if (Array.isArray(data)) setStats({ total: data.length, completed: data.filter((a: any) => a.status === 'completed').length });
    } catch { }
  };

  const handleSignOut = () => {
    Alert.alert('Sign Out', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign Out', style: 'destructive',
        onPress: async () => {
          await AsyncStorage.multiRemove(['token', 'user']);
          // Replace ensures back button won't bring user back
          router.replace('/');
        }
      }
    ]);
  };

  return (
    <View style={ps.root}>
      <StatusBar barStyle="light-content" />
      <ScrollView showsVerticalScrollIndicator={false}>
        <View style={ps.header}>
          <Text style={ps.title}>Profile</Text>
        </View>

        <View style={ps.profileCard}>
          <View style={ps.avatar}><Text style={ps.avatarText}>{user?.name?.[0]?.toUpperCase() || 'U'}</Text></View>
          <Text style={ps.name}>{user?.name || 'User'}</Text>
          <Text style={ps.email}>{user?.email || ''}</Text>
          <View style={ps.statsRow}>
            <View style={ps.statItem}><Text style={ps.statVal}>{stats.total}</Text><Text style={ps.statLbl}>Total</Text></View>
            <View style={ps.statDivider} />
            <View style={ps.statItem}><Text style={ps.statVal}>{stats.completed}</Text><Text style={ps.statLbl}>Done</Text></View>
            <View style={ps.statDivider} />
            <View style={ps.statItem}><Text style={ps.statVal}>{stats.total - stats.completed}</Text><Text style={ps.statLbl}>Failed</Text></View>
          </View>
        </View>

        <View style={ps.menuCard}>
          {[
            { icon: '📊', label: 'My Analyses', sub: `${stats.completed} completed`, onPress: () => router.push('/(tabs)/history') },
            { icon: '🔗', label: 'Share FinSight', sub: 'Invite others', onPress: () => {} },
            { icon: '📧', label: 'Support', sub: 'Get help', onPress: () => {} },
          ].map((item, i) => (
            <TouchableOpacity key={i} style={[ps.menuItem, { borderBottomColor: 'rgba(255,255,255,0.05)' }]} onPress={item.onPress}>
              <View style={ps.menuLeft}>
                <View style={ps.menuIcon}><Text style={{ fontSize: 16 }}>{item.icon}</Text></View>
                <View>
                  <Text style={ps.menuLabel}>{item.label}</Text>
                  <Text style={ps.menuSub}>{item.sub}</Text>
                </View>
              </View>
              <Text style={ps.menuArrow}>›</Text>
            </TouchableOpacity>
          ))}
        </View>

        <TouchableOpacity style={ps.signOutBtn} onPress={handleSignOut}>
          <Text style={ps.signOutText}>Sign Out</Text>
        </TouchableOpacity>

        <Text style={ps.version}>FinSight · AI Financial Analysis</Text>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const ps = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#030B1A' },
  header: { paddingHorizontal: 24, paddingTop: 60, paddingBottom: 20 },
  title: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: -0.8 },
  profileCard: { marginHorizontal: 20, backgroundColor: '#0D1426', borderRadius: 24, padding: 28, alignItems: 'center', marginBottom: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' },
  avatar: { width: 76, height: 76, borderRadius: 38, backgroundColor: '#4F8AFF', alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  avatarText: { color: '#fff', fontSize: 30, fontWeight: '800' },
  name: { color: '#fff', fontSize: 20, fontWeight: '800', marginBottom: 4 },
  email: { color: 'rgba(255,255,255,0.35)', fontSize: 13, marginBottom: 22 },
  statsRow: { flexDirection: 'row', alignItems: 'center' },
  statItem: { alignItems: 'center', paddingHorizontal: 22 },
  statVal: { color: '#fff', fontSize: 24, fontWeight: '900' },
  statLbl: { color: 'rgba(255,255,255,0.3)', fontSize: 11, marginTop: 2 },
  statDivider: { width: 1, height: 36, backgroundColor: 'rgba(255,255,255,0.07)' },
  menuCard: { marginHorizontal: 20, backgroundColor: '#0D1426', borderRadius: 20, overflow: 'hidden', marginBottom: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)' },
  menuItem: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 18, paddingVertical: 17, borderBottomWidth: 1 },
  menuLeft: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  menuIcon: { width: 38, height: 38, borderRadius: 11, backgroundColor: 'rgba(255,255,255,0.05)', alignItems: 'center', justifyContent: 'center' },
  menuLabel: { color: '#fff', fontSize: 15, fontWeight: '600' },
  menuSub: { color: 'rgba(255,255,255,0.28)', fontSize: 12, marginTop: 1 },
  menuArrow: { color: 'rgba(255,255,255,0.18)', fontSize: 24 },
  signOutBtn: { marginHorizontal: 20, backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 18, padding: 17, alignItems: 'center', borderWidth: 1, borderColor: 'rgba(239,68,68,0.22)', marginBottom: 20 },
  signOutText: { color: '#ef4444', fontSize: 15, fontWeight: '700' },
  version: { textAlign: 'center', color: 'rgba(255,255,255,0.12)', fontSize: 11 },
});
