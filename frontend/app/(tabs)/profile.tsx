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
