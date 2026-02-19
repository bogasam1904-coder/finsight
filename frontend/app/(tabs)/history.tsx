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
                <Text style={styles.meta}>{item.result?.statement_type?.replace("_", " ") || item.file_type.toUpperCase()} Â· {new Date(item.created_at).toLocaleDateString()}</Text>
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
