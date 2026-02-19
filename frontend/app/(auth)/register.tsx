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
