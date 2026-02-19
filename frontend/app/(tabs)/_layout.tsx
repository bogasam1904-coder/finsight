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
