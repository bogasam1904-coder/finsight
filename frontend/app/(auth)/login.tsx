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
                <TextInput style={styles.input} placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢" placeholderTextColor="#BBBBBB" secureTextEntry={!showPw} value={password} onChangeText={t => { setPassword(t); setErrors(p => ({ ...p, password: "" })); }} />
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
