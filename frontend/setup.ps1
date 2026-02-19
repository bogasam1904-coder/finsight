# Run this from C:\Users\Sameer\finsight\frontend
# PS> .\setup.ps1

$files = @{}

$files["src/api.ts"] = @'
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || 'http://localhost:8001';

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = await AsyncStorage.getItem('session_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(`${BASE_URL}/api${path}`, { ...options, headers, credentials: 'include' });
}

export async function saveToken(token: string) {
  await AsyncStorage.setItem('session_token', token);
}

export async function clearToken() {
  await AsyncStorage.removeItem('session_token');
}

export async function getToken(): Promise<string | null> {
  return AsyncStorage.getItem('session_token');
}
'@

$files["src/context/AuthContext.tsx"] = @'
import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { apiFetch, saveToken, clearToken } from '../api';

interface User { user_id: string; name: string; email: string; }
interface AuthContextType {
  user: User | null; loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { checkSession(); }, []);

  const checkSession = async () => {
    try {
      const res = await apiFetch('/auth/me');
      if (res.ok) setUser(await res.json());
    } catch (e) {} finally { setLoading(false); }
  };

  const login = async (email: string, password: string) => {
    const res = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Login failed'); }
    const data = await res.json();
    await saveToken(data.token);
    setUser({ user_id: data.user_id, name: data.name, email: data.email });
  };

  const register = async (name: string, email: string, password: string) => {
    const res = await apiFetch('/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Registration failed'); }
    const data = await res.json();
    await saveToken(data.token);
    setUser({ user_id: data.user_id, name: data.name, email: data.email });
  };

  const logout = async () => { await clearToken(); setUser(null); };

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
'@

$files["app/_layout.tsx"] = @'
import { useEffect } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { View, ActivityIndicator } from 'react-native';

function RootLayoutNav() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    if (loading) return;
    const inAuthGroup = segments[0] === '(auth)';
    if (!user && !inAuthGroup) router.replace('/(auth)/login');
    else if (user && inAuthGroup) router.replace('/(tabs)');
  }, [user, loading, segments]);

  if (loading) return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff' }}>
      <ActivityIndicator size="large" color="#0052FF" />
    </View>
  );

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="analysis/[id]" options={{ presentation: 'card' }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <RootLayoutNav />
    </AuthProvider>
  );
}
'@

$files["app/(auth)/_layout.tsx"] = @'
import { Stack } from 'expo-router';
export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
'@

$files["app/(auth)/login.tsx"] = @'
import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useAuth } from "../../src/context/AuthContext";

export default function LoginScreen() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = () => {
    const e: Record<string, string> = {};
    if (!email.trim()) e.email = "Email is required";
    else if (!/\S+@\S+\.\S+/.test(email)) e.email = "Enter a valid email";
    if (!password) e.password = "Password is required";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleLogin = async () => {
    if (!validate()) return;
    setLoading(true);
    try { await login(email.trim().toLowerCase(), password); }
    catch (e: any) { Alert.alert("Login Failed", e.message || "Please check your credentials"); }
    finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <View style={styles.logo}><Feather name="bar-chart-2" size={32} color="#FFFFFF" /></View>
            <Text style={styles.appName}>FinSight</Text>
            <Text style={styles.tagline}>AI-powered financial analysis</Text>
          </View>
          <View style={styles.card}>
            <Text style={styles.title}>Welcome back</Text>
            <Text style={styles.subtitle}>Sign in to your account</Text>
            <View style={styles.fieldGroup}>
              <Text style={styles.label}>Email</Text>
              <View style={[styles.inputWrap, errors.email && styles.inputError]}>
                <Feather name="mail" size={18} color="#888" style={styles.inputIcon} />
                <TextInput style={styles.input} placeholder="you@example.com" placeholderTextColor="#BBBBBB" keyboardType="email-address" autoCapitalize="none" value={email} onChangeText={t => { setEmail(t); setErrors(p => ({ ...p, email: "" })); }} />
              </View>
              {errors.email ? <Text style={styles.errorText}>{errors.email}</Text> : null}
            </View>
            <View style={styles.fieldGroup}>
              <Text style={styles.label}>Password</Text>
              <View style={[styles.inputWrap, errors.password && styles.inputError]}>
                <Feather name="lock" size={18} color="#888" style={styles.inputIcon} />
                <TextInput style={styles.input} placeholder="••••••••" placeholderTextColor="#BBBBBB" secureTextEntry={!showPw} value={password} onChangeText={t => { setPassword(t); setErrors(p => ({ ...p, password: "" })); }} />
                <TouchableOpacity onPress={() => setShowPw(v => !v)} style={styles.eyeBtn}><Feather name={showPw ? "eye-off" : "eye"} size={18} color="#888" /></TouchableOpacity>
              </View>
              {errors.password ? <Text style={styles.errorText}>{errors.password}</Text> : null}
            </View>
            <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={handleLogin} disabled={loading} activeOpacity={0.85}>
              {loading ? <ActivityIndicator color="#FFF" /> : <Text style={styles.btnText}>Sign In</Text>}
            </TouchableOpacity>
            <View style={styles.divider}><View style={styles.dividerLine} /><Text style={styles.dividerText}>or</Text><View style={styles.dividerLine} /></View>
            <TouchableOpacity style={styles.secondaryBtn} onPress={() => router.push("/(auth)/register")} activeOpacity={0.85}>
              <Text style={styles.secondaryBtnText}>Create an account</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F7FF" },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 40 },
  header: { alignItems: "center", paddingTop: 48, paddingBottom: 32 },
  logo: { width: 72, height: 72, borderRadius: 22, backgroundColor: "#0052FF", justifyContent: "center", alignItems: "center", marginBottom: 12 },
  appName: { fontSize: 28, fontWeight: "800", color: "#111111" },
  tagline: { fontSize: 15, color: "#888888", marginTop: 4, fontWeight: "500" },
  card: { backgroundColor: "#FFFFFF", borderRadius: 24, padding: 28 },
  title: { fontSize: 24, fontWeight: "800", color: "#111111", marginBottom: 4 },
  subtitle: { fontSize: 15, color: "#888888", marginBottom: 28, fontWeight: "500" },
  fieldGroup: { marginBottom: 16 },
  label: { fontSize: 14, fontWeight: "600", color: "#444444", marginBottom: 8 },
  inputWrap: { flexDirection: "row", alignItems: "center", borderWidth: 1.5, borderColor: "#E5E5E5", borderRadius: 14, backgroundColor: "#FAFAFA", paddingHorizontal: 14 },
  inputError: { borderColor: "#FF3B30" },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, height: 50, fontSize: 16, color: "#111111" },
  eyeBtn: { padding: 4 },
  errorText: { color: "#FF3B30", fontSize: 12, marginTop: 4, fontWeight: "500" },
  btn: { backgroundColor: "#0052FF", borderRadius: 14, height: 52, justifyContent: "center", alignItems: "center", marginTop: 8 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#FFFFFF", fontSize: 16, fontWeight: "700" },
  divider: { flexDirection: "row", alignItems: "center", marginVertical: 20 },
  dividerLine: { flex: 1, height: 1, backgroundColor: "#EEEEEE" },
  dividerText: { marginHorizontal: 12, color: "#AAAAAA", fontSize: 14, fontWeight: "500" },
  secondaryBtn: { borderWidth: 1.5, borderColor: "#E5E5E5", borderRadius: 14, height: 52, justifyContent: "center", alignItems: "center" },
  secondaryBtnText: { color: "#111111", fontSize: 16, fontWeight: "600" },
});
'@

$files["app/(auth)/register.tsx"] = @'
import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useAuth } from "../../src/context/AuthContext";

export default function RegisterScreen() {
  const router = useRouter();
  const { register } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = () => {
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = "Name is required";
    if (!email.trim()) e.email = "Email is required";
    else if (!/\S+@\S+\.\S+/.test(email)) e.email = "Enter a valid email";
    if (!password) e.password = "Password is required";
    else if (password.length < 8) e.password = "Password must be at least 8 characters";
    if (password !== confirm) e.confirm = "Passwords do not match";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleRegister = async () => {
    if (!validate()) return;
    setLoading(true);
    try { await register(name.trim(), email.trim().toLowerCase(), password); }
    catch (e: any) { Alert.alert("Registration Failed", e.message || "Please try again"); }
    finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <TouchableOpacity style={styles.back} onPress={() => router.back()}><Feather name="arrow-left" size={22} color="#111111" /></TouchableOpacity>
          <View style={styles.headerText}>
            <Text style={styles.title}>Create account</Text>
            <Text style={styles.subtitle}>Start analyzing financial statements for free</Text>
          </View>
          <View style={styles.card}>
            {[
              { label: "Full name", value: name, onChange: setName, placeholder: "Jane Smith", icon: "user", key: "name", secure: false },
              { label: "Email", value: email, onChange: setEmail, placeholder: "you@example.com", icon: "mail", key: "email", secure: false },
              { label: "Password", value: password, onChange: setPassword, placeholder: "Min 8 characters", icon: "lock", key: "password", secure: true },
              { label: "Confirm password", value: confirm, onChange: setConfirm, placeholder: "Re-enter password", icon: "lock", key: "confirm", secure: true },
            ].map(f => (
              <View key={f.key} style={styles.fieldGroup}>
                <Text style={styles.label}>{f.label}</Text>
                <View style={[styles.inputWrap, errors[f.key] && styles.inputError]}>
                  <Feather name={f.icon as any} size={18} color="#888" style={styles.inputIcon} />
                  <TextInput style={styles.input} placeholder={f.placeholder} placeholderTextColor="#BBBBBB" secureTextEntry={f.secure && !showPw} autoCapitalize="none" value={f.value} onChangeText={t => { f.onChange(t); setErrors(p => ({ ...p, [f.key]: "" })); }} />
                  {f.secure && <TouchableOpacity onPress={() => setShowPw(v => !v)} style={styles.eyeBtn}><Feather name={showPw ? "eye-off" : "eye"} size={18} color="#888" /></TouchableOpacity>}
                </View>
                {errors[f.key] ? <Text style={styles.errorText}>{errors[f.key]}</Text> : null}
              </View>
            ))}
            <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={handleRegister} disabled={loading} activeOpacity={0.85}>
              {loading ? <ActivityIndicator color="#FFF" /> : <Text style={styles.btnText}>Create Account</Text>}
            </TouchableOpacity>
            <TouchableOpacity style={styles.loginLink} onPress={() => router.push("/(auth)/login")}>
              <Text style={styles.loginLinkText}>Already have an account? <Text style={{ color: "#0052FF", fontWeight: "700" }}>Sign in</Text></Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F7FF" },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 40 },
  back: { paddingTop: 16, paddingBottom: 8, alignSelf: "flex-start" },
  headerText: { paddingTop: 12, paddingBottom: 28 },
  title: { fontSize: 28, fontWeight: "800", color: "#111111" },
  subtitle: { fontSize: 15, color: "#888888", marginTop: 6, fontWeight: "500" },
  card: { backgroundColor: "#FFFFFF", borderRadius: 24, padding: 28 },
  fieldGroup: { marginBottom: 16 },
  label: { fontSize: 14, fontWeight: "600", color: "#444444", marginBottom: 8 },
  inputWrap: { flexDirection: "row", alignItems: "center", borderWidth: 1.5, borderColor: "#E5E5E5", borderRadius: 14, backgroundColor: "#FAFAFA", paddingHorizontal: 14 },
  inputError: { borderColor: "#FF3B30" },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, height: 50, fontSize: 16, color: "#111111" },
  eyeBtn: { padding: 4 },
  errorText: { color: "#FF3B30", fontSize: 12, marginTop: 4, fontWeight: "500" },
  btn: { backgroundColor: "#0052FF", borderRadius: 14, height: 52, justifyContent: "center", alignItems: "center", marginTop: 8 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#FFFFFF", fontSize: 16, fontWeight: "700" },
  loginLink: { marginTop: 20, alignItems: "center" },
  loginLinkText: { fontSize: 14, color: "#666666", fontWeight: "500" },
});
'@

$files["app/(tabs)/_layout.tsx"] = @'
import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";

export default function TabLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: "#0052FF", tabBarInactiveTintColor: "#AAAAAA", tabBarStyle: { backgroundColor: "#FFFFFF", borderTopWidth: 1, borderTopColor: "#F0F0F0", paddingBottom: 8, paddingTop: 8, height: 64 }, tabBarLabelStyle: { fontSize: 11, fontWeight: "600", marginTop: 2 } }}>
      <Tabs.Screen name="index" options={{ title: "Analyze", tabBarIcon: ({ color, size }) => <Feather name="upload-cloud" size={size} color={color} /> }} />
      <Tabs.Screen name="history" options={{ title: "History", tabBarIcon: ({ color, size }) => <Feather name="clock" size={size} color={color} /> }} />
      <Tabs.Screen name="profile" options={{ title: "Profile", tabBarIcon: ({ color, size }) => <Feather name="user" size={size} color={color} /> }} />
    </Tabs>
  );
}
'@

$files["app/(tabs)/history.tsx"] = @'
import { useState, useCallback } from "react";
import { View, Text, FlatList, TouchableOpacity, StyleSheet, ActivityIndicator, RefreshControl, Alert } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { apiFetch } from "../../src/api";

interface Analysis { analysis_id: string; filename: string; file_type: string; status: string; created_at: string; result?: { company_name?: string; health_score?: number; statement_type?: string; }; }

export default function HistoryScreen() {
  const router = useRouter();
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try { const res = await apiFetch("/analyses"); if (res.ok) setAnalyses(await res.json()); }
    catch (e) {} finally { setLoading(false); setRefreshing(false); }
  };

  useFocusEffect(useCallback(() => { load(); }, []));

  const handleDelete = (id: string) => {
    Alert.alert("Delete", "Remove this analysis?", [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => { await apiFetch(`/analyses/${id}`, { method: "DELETE" }); setAnalyses(prev => prev.filter(a => a.analysis_id !== id)); } },
    ]);
  };

  if (loading) return <SafeAreaView style={styles.container}><View style={styles.center}><ActivityIndicator size="large" color="#0052FF" /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}><Text style={styles.headerTitle}>History</Text><Text style={styles.headerSub}>{analyses.length} analyses</Text></View>
      {analyses.length === 0 ? (
        <View style={styles.empty}>
          <Feather name="inbox" size={48} color="#CCCCCC" />
          <Text style={styles.emptyTitle}>No analyses yet</Text>
          <Text style={styles.emptyText}>Upload a financial statement to get started</Text>
          <TouchableOpacity style={styles.emptyBtn} onPress={() => router.push("/(tabs)")}><Text style={styles.emptyBtnText}>Upload Now</Text></TouchableOpacity>
        </View>
      ) : (
        <FlatList data={analyses} keyExtractor={item => item.analysis_id} contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor="#0052FF" />}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          renderItem={({ item }) => (
            <TouchableOpacity style={styles.card} onPress={() => item.status === "completed" && router.push(`/analysis/${item.analysis_id}`)} onLongPress={() => handleDelete(item.analysis_id)} activeOpacity={0.8}>
              <View style={styles.iconWrap}><Feather name={item.file_type === "pdf" ? "file-text" : "image"} size={22} color="#0052FF" /></View>
              <View style={styles.cardContent}>
                <Text style={styles.companyName} numberOfLines={1}>{item.result?.company_name || item.filename}</Text>
                <Text style={styles.meta}>{item.result?.statement_type?.replace("_", " ") || item.file_type.toUpperCase()} · {new Date(item.created_at).toLocaleDateString()}</Text>
              </View>
              <View style={[styles.statusDot, { backgroundColor: item.status === "completed" ? "#00C853" : item.status === "processing" ? "#FFAB00" : "#FF3B30" }]} />
            </TouchableOpacity>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  header: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: "#F0F0F0" },
  headerTitle: { fontSize: 28, fontWeight: "800", color: "#111111" },
  headerSub: { fontSize: 13, color: "#888888", fontWeight: "500", marginTop: 2 },
  list: { padding: 16 },
  card: { flexDirection: "row", alignItems: "center", backgroundColor: "#F8F9FA", borderRadius: 16, padding: 16, gap: 12 },
  iconWrap: { width: 46, height: 46, borderRadius: 13, backgroundColor: "#EEF3FF", justifyContent: "center", alignItems: "center" },
  cardContent: { flex: 1 },
  companyName: { fontSize: 15, fontWeight: "700", color: "#111111", marginBottom: 3 },
  meta: { fontSize: 13, color: "#888888", fontWeight: "500" },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  empty: { flex: 1, justifyContent: "center", alignItems: "center", gap: 12, padding: 40 },
  emptyTitle: { fontSize: 20, fontWeight: "700", color: "#111111" },
  emptyText: { fontSize: 15, color: "#888888", textAlign: "center", lineHeight: 22 },
  emptyBtn: { marginTop: 8, backgroundColor: "#0052FF", borderRadius: 14, paddingHorizontal: 24, paddingVertical: 12 },
  emptyBtnText: { color: "#FFFFFF", fontWeight: "700", fontSize: 15 },
});
'@

$files["app/(tabs)/profile.tsx"] = @'
import { View, Text, TouchableOpacity, StyleSheet, Alert, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useAuth } from "../../src/context/AuthContext";

export default function ProfileScreen() {
  const { user, logout } = useAuth();
  const handleLogout = () => Alert.alert("Sign Out", "Are you sure?", [{ text: "Cancel", style: "cancel" }, { text: "Sign Out", style: "destructive", onPress: logout }]);

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.header}><Text style={styles.headerTitle}>Profile</Text></View>
        <View style={styles.profileCard}>
          <View style={styles.avatar}><Text style={styles.avatarText}>{user?.name?.charAt(0).toUpperCase() || "?"}</Text></View>
          <Text style={styles.userName}>{user?.name || "User"}</Text>
          <Text style={styles.userEmail}>{user?.email || ""}</Text>
        </View>
        <View style={styles.section}>
          <View style={styles.menuCard}>
            <TouchableOpacity style={styles.menuItem} onPress={handleLogout}>
              <View style={[styles.menuIcon, { backgroundColor: "#FFF0F0" }]}><Feather name="log-out" size={18} color="#FF3B30" /></View>
              <Text style={[styles.menuLabel, { color: "#FF3B30" }]}>Sign Out</Text>
            </TouchableOpacity>
          </View>
        </View>
        <Text style={styles.version}>FinSight v1.0.0</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  scroll: { paddingBottom: 40 },
  header: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12 },
  headerTitle: { fontSize: 28, fontWeight: "800", color: "#111111" },
  profileCard: { alignItems: "center", paddingVertical: 28, borderBottomWidth: 1, borderBottomColor: "#F0F0F0", marginBottom: 24 },
  avatar: { width: 80, height: 80, borderRadius: 40, backgroundColor: "#0052FF", justifyContent: "center", alignItems: "center", marginBottom: 12 },
  avatarText: { fontSize: 32, fontWeight: "800", color: "#FFFFFF" },
  userName: { fontSize: 20, fontWeight: "700", color: "#111111" },
  userEmail: { fontSize: 14, color: "#888888", marginTop: 4, fontWeight: "500" },
  section: { paddingHorizontal: 20, marginBottom: 20 },
  menuCard: { backgroundColor: "#F8F9FA", borderRadius: 16, overflow: "hidden" },
  menuItem: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 15, gap: 14 },
  menuIcon: { width: 34, height: 34, borderRadius: 10, justifyContent: "center", alignItems: "center" },
  menuLabel: { flex: 1, fontSize: 15, fontWeight: "600", color: "#111111" },
  version: { textAlign: "center", color: "#CCCCCC", fontSize: 12, marginTop: 16 },
});
'@

$files["app/analysis/[id].tsx"] = @'
import { useEffect, useState } from "react";
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { apiFetch } from "../../src/api";

export default function AnalysisScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadAnalysis(); }, [id]);

  const loadAnalysis = async () => {
    try { const res = await apiFetch(`/analyses/${id}`); if (!res.ok) throw new Error("Not found"); setAnalysis(await res.json()); }
    catch (e) { Alert.alert("Error", "Could not load analysis", [{ text: "Go back", onPress: () => router.back() }]); }
    finally { setLoading(false); }
  };

  if (loading) return <SafeAreaView style={styles.container}><View style={styles.center}><ActivityIndicator size="large" color="#0052FF" /></View></SafeAreaView>;
  if (!analysis) return null;

  const r = analysis.result;

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={22} color="#111" /></TouchableOpacity>
        <View style={styles.headerCenter}>
          <Text style={styles.headerTitle} numberOfLines={1}>{r?.company_name || analysis.filename}</Text>
          <Text style={styles.headerSub}>{r?.statement_type?.replace("_", " ").toUpperCase() || "Financial Statement"}{r?.period ? ` · ${r.period}` : ""}</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        {r && (
          <>
            <View style={styles.summaryCard}>
              <Text style={styles.sectionLabel}>Summary</Text>
              <Text style={styles.summaryText}>{r.summary || "No summary available."}</Text>
              {r.health_score != null && (
                <View style={styles.scoreRow}>
                  <Text style={styles.scoreLabel}>Health Score</Text>
                  <Text style={[styles.scoreValue, { color: r.health_score >= 75 ? "#00C853" : r.health_score >= 50 ? "#FFAB00" : "#FF3B30" }]}>{r.health_score}/100 — {r.health_label}</Text>
                </View>
              )}
            </View>
            {r.key_metrics?.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Key Metrics</Text>
                <View style={styles.metricsGrid}>
                  {r.key_metrics.map((m: any, i: number) => (
                    <View key={i} style={styles.metricCard}>
                      <Text style={styles.metricLabel}>{m.label}</Text>
                      <Text style={styles.metricValue}>{m.value}</Text>
                      {m.change && <Text style={{ fontSize: 12, color: m.trend === "up" ? "#00C853" : m.trend === "down" ? "#FF3B30" : "#888" }}>{m.change}</Text>}
                    </View>
                  ))}
                </View>
              </View>
            )}
            {r.highlights?.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Highlights</Text>
                {r.highlights.map((h: string, i: number) => (
                  <View key={i} style={styles.bulletRow}><View style={[styles.bullet, { backgroundColor: "#00C853" }]} /><Text style={styles.bulletText}>{h}</Text></View>
                ))}
              </View>
            )}
            {r.risks?.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Risks</Text>
                {r.risks.map((risk: string, i: number) => (
                  <View key={i} style={styles.bulletRow}><View style={[styles.bullet, { backgroundColor: "#FF3B30" }]} /><Text style={styles.bulletText}>{risk}</Text></View>
                ))}
              </View>
            )}
          </>
        )}
        <Text style={styles.footer}>Analyzed {new Date(analysis.created_at).toLocaleString()}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: "#F0F0F0" },
  backBtn: { padding: 4, marginRight: 8 },
  headerCenter: { flex: 1 },
  headerTitle: { fontSize: 17, fontWeight: "700", color: "#111111" },
  headerSub: { fontSize: 12, color: "#888888", marginTop: 2, fontWeight: "500" },
  scroll: { paddingBottom: 40 },
  summaryCard: { margin: 16, padding: 20, backgroundColor: "#F0F4FF", borderRadius: 20 },
  sectionLabel: { fontSize: 11, fontWeight: "700", color: "#0052FF", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 },
  summaryText: { fontSize: 14, color: "#333333", lineHeight: 21, fontWeight: "500" },
  scoreRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: "#DCE6FF" },
  scoreLabel: { fontSize: 14, fontWeight: "600", color: "#444" },
  scoreValue: { fontSize: 14, fontWeight: "800" },
  section: { paddingHorizontal: 16, marginBottom: 24 },
  sectionTitle: { fontSize: 13, fontWeight: "700", color: "#888888", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 },
  metricsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metricCard: { width: "47%", backgroundColor: "#F8F9FA", borderRadius: 14, padding: 16, gap: 4 },
  metricLabel: { fontSize: 12, color: "#888888", fontWeight: "600" },
  metricValue: { fontSize: 20, fontWeight: "800", color: "#111111" },
  bulletRow: { flexDirection: "row", gap: 12, marginBottom: 10, alignItems: "flex-start" },
  bullet: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  bulletText: { flex: 1, fontSize: 15, color: "#333333", lineHeight: 22 },
  footer: { textAlign: "center", color: "#BBBBBB", fontSize: 12, marginTop: 8 },
});
'@

# Write all files
foreach ($path in $files.Keys) {
    $dir = Split-Path $path -Parent
    if ($dir -and !(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -Path $path -Value $files[$path] -Encoding UTF8
    Write-Host "Created: $path" -ForegroundColor Green
}

Write-Host "`nAll files created successfully!" -ForegroundColor Cyan
