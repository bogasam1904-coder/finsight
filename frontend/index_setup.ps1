$content = @'
import { useState, useEffect } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Platform, ScrollView, Alert } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { apiFetch } from "../../src/api";

export default function HomeScreen() {
  const router = useRouter();
  const [userName, setUserName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [recentAnalyses, setRecentAnalyses] = useState<any[]>([]);

  useEffect(() => { loadUserData(); loadRecentAnalyses(); }, []);

  const loadUserData = async () => {
    try { const res = await apiFetch("/auth/me"); if (res.ok) { const user = await res.json(); setUserName(user.name?.split(" ")[0] || "there"); } } catch (e) {}
  };

  const loadRecentAnalyses = async () => {
    try { const res = await apiFetch("/analyses"); if (res.ok) { const data = await res.json(); setRecentAnalyses(data.slice(0, 3)); } } catch (e) {}
  };

  const handleUploadPDF = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "image/jpeg", "image/png"], copyToCacheDirectory: true });
      if (!result.canceled && result.assets?.[0]) {
        const asset = result.assets[0];
        await processUpload(asset.uri, asset.name || "document", asset.mimeType || "application/pdf", (asset as any).file);
      }
    } catch (e) { Alert.alert("Error", "Failed to pick document"); }
  };

  const handlePickImage = async () => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.8 });
      if (!result.canceled && result.assets?.[0]) {
        const asset = result.assets[0];
        await processUpload(asset.uri, asset.fileName || "image.jpg", asset.mimeType || "image/jpeg", undefined);
      }
    } catch (e) { Alert.alert("Error", "Failed to pick image"); }
  };

  const processUpload = async (uri: string, name: string, mimeType: string, fileObj?: File) => {
    setUploading(true);
    setUploadProgress("Uploading file...");
    try {
      const formData = new FormData();
      if (Platform.OS === "web" && fileObj) { formData.append("file", fileObj); }
      else if (Platform.OS === "web") { const blob = await fetch(uri).then(r => r.blob()); formData.append("file", blob, name); }
      else { formData.append("file", { uri, name, type: mimeType } as any); }

      const token = await AsyncStorage.getItem("session_token");
      const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL;
      setUploadProgress("AI is analyzing your financial statement...");

      const response = await fetch(`${BASE_URL}/api/analyze`, {
        method: "POST", body: formData,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });

      if (!response.ok) { const err = await response.json().catch(() => ({ detail: "Upload failed" })); throw new Error(err.detail || "Upload failed"); }
      const result = await response.json();
      if (result.status === "failed") { Alert.alert("Analysis Failed", result.message || "Could not process the file."); return; }
      setUploadProgress("Analysis complete!");
      router.push(`/analysis/${result.analysis_id}`);
    } catch (e: any) { Alert.alert("Error", e.message || "Failed to analyze document"); }
    finally { setUploading(false); setUploadProgress(""); }
  };

  if (uploading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.uploadingContainer}>
          <View style={styles.uploadingCard}>
            <ActivityIndicator size="large" color="#0052FF" />
            <Text style={styles.uploadingTitle}>Analyzing</Text>
            <Text style={styles.uploadingProgress}>{uploadProgress}</Text>
            <Text style={styles.uploadingHint}>This may take 30-60 seconds</Text>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.header}>
          <Text style={styles.greeting}>Hi, {userName || "there"}</Text>
          <Text style={styles.headerTitle}>What do you want{"\n"}to analyze today?</Text>
        </View>
        <View style={styles.uploadSection}>
          <TouchableOpacity style={styles.uploadCard} onPress={handleUploadPDF} activeOpacity={0.85}>
            <View style={styles.uploadIconContainer}><Feather name="upload-cloud" size={32} color="#0052FF" /></View>
            <Text style={styles.uploadCardTitle}>Upload Document</Text>
            <Text style={styles.uploadCardDesc}>PDF, JPEG, or PNG</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.uploadSmallCard} onPress={handlePickImage} activeOpacity={0.85}>
            <Feather name="image" size={24} color="#111111" />
            <Text style={styles.smallCardLabel}>From Gallery</Text>
          </TouchableOpacity>
        </View>
        {recentAnalyses.length > 0 && (
          <View style={styles.recentSection}>
            <Text style={styles.sectionTitle}>Recent Analyses</Text>
            {recentAnalyses.map((analysis) => (
              <TouchableOpacity key={analysis.analysis_id} style={styles.recentCard} onPress={() => analysis.status === "completed" && router.push(`/analysis/${analysis.analysis_id}`)} activeOpacity={0.85}>
                <View style={styles.recentCardLeft}><Feather name={analysis.file_type === "pdf" ? "file-text" : "image"} size={20} color="#555555" /></View>
                <View style={styles.recentCardContent}>
                  <Text style={styles.recentFileName} numberOfLines={1}>{analysis.filename}</Text>
                  <Text style={styles.recentDate}>{new Date(analysis.created_at).toLocaleDateString()}</Text>
                </View>
                <View style={[styles.statusDot, { backgroundColor: analysis.status === "completed" ? "#00C853" : analysis.status === "processing" ? "#FFAB00" : "#FF3B30" }]} />
              </TouchableOpacity>
            ))}
          </View>
        )}
        <View style={styles.tipsSection}>
          <View style={styles.tipCard}>
            <Feather name="info" size={16} color="#0052FF" />
            <Text style={styles.tipText}>For best results, upload clear PDFs or high-resolution photos of financial statements.</Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  scrollContent: { paddingHorizontal: 20, paddingBottom: 32 },
  header: { paddingTop: 16, marginBottom: 32 },
  greeting: { fontSize: 16, color: "#888888", fontWeight: "500", marginBottom: 4 },
  headerTitle: { fontSize: 32, fontWeight: "800", color: "#111111", letterSpacing: -0.5, lineHeight: 38 },
  uploadSection: { marginBottom: 32, gap: 12 },
  uploadCard: { backgroundColor: "#F8F9FA", borderRadius: 20, padding: 32, alignItems: "center", borderWidth: 2, borderColor: "#E5E5E5", borderStyle: "dashed" },
  uploadIconContainer: { width: 64, height: 64, borderRadius: 20, backgroundColor: "#FFFFFF", justifyContent: "center", alignItems: "center", marginBottom: 16, borderWidth: 1, borderColor: "#E5E5E5" },
  uploadCardTitle: { fontSize: 18, fontWeight: "700", color: "#111111", marginBottom: 4 },
  uploadCardDesc: { fontSize: 14, color: "#888888", fontWeight: "500" },
  uploadSmallCard: { backgroundColor: "#F8F9FA", borderRadius: 16, padding: 20, alignItems: "center", gap: 8, borderWidth: 1, borderColor: "#E5E5E5" },
  smallCardLabel: { fontSize: 14, fontWeight: "600", color: "#111111" },
  recentSection: { marginBottom: 32 },
  sectionTitle: { fontSize: 14, fontWeight: "700", color: "#888888", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 },
  recentCard: { flexDirection: "row", alignItems: "center", backgroundColor: "#F8F9FA", borderRadius: 12, padding: 16, marginBottom: 8 },
  recentCardLeft: { width: 40, height: 40, borderRadius: 10, backgroundColor: "#FFFFFF", justifyContent: "center", alignItems: "center", marginRight: 12, borderWidth: 1, borderColor: "#E5E5E5" },
  recentCardContent: { flex: 1 },
  recentFileName: { fontSize: 15, fontWeight: "600", color: "#111111", marginBottom: 2 },
  recentDate: { fontSize: 13, color: "#888888" },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  tipsSection: { marginBottom: 16 },
  tipCard: { flexDirection: "row", backgroundColor: "#F0F4FF", borderRadius: 12, padding: 16, gap: 12, alignItems: "flex-start" },
  tipText: { flex: 1, fontSize: 14, color: "#555555", lineHeight: 20 },
  uploadingContainer: { flex: 1, justifyContent: "center", alignItems: "center", paddingHorizontal: 32 },
  uploadingCard: { backgroundColor: "#F8F9FA", borderRadius: 24, padding: 48, alignItems: "center", width: "100%", gap: 16 },
  uploadingTitle: { fontSize: 24, fontWeight: "800", color: "#111111" },
  uploadingProgress: { fontSize: 16, color: "#0052FF", fontWeight: "600", textAlign: "center" },
  uploadingHint: { fontSize: 14, color: "#888888", textAlign: "center", lineHeight: 20 },
});
'@

Set-Content -Path "app/(tabs)/index.tsx" -Value $content -Encoding UTF8
Write-Host "index.tsx created!" -ForegroundColor Green
