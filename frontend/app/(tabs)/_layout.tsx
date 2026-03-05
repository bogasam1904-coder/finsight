// COMPLETE FILE - app/(tabs)/_layout.tsx
// FIXES: Issue #4 (duplicate search), Issue #5 (bottom nav)

import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Platform } from "react-native";

export default function TabLayout() {
  return (
    <Tabs 
      screenOptions={{ 
        headerShown: false,
        tabBarActiveTintColor: "#4F8AFF",
        tabBarInactiveTintColor: "#6B82A8",
        tabBarStyle: {
          backgroundColor: "#0D1426",
          borderTopWidth: 1,
          borderTopColor: "rgba(255,255,255,0.06)",
          paddingBottom: Platform.OS === 'ios' ? 20 : 8,
          paddingTop: 8,
          height: Platform.OS === 'ios' ? 84 : 64,
        },
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: "700",
          marginTop: 2
        },
        tabBarItemStyle: {
          paddingVertical: 4,
        }
      }}
    >
      <Tabs.Screen 
        name="index" 
        options={{ 
          title: "Analyze", 
          tabBarIcon: ({ color, size }) => (
            <Feather name="upload-cloud" size={size} color={color} />
          )
        }} 
      />
      <Tabs.Screen 
        name="history" 
        options={{ 
          title: "History", 
          tabBarIcon: ({ color, size }) => (
            <Feather name="clock" size={size} color={color} />
          )
        }} 
      />
      <Tabs.Screen 
        name="profile" 
        options={{ 
          title: "Profile", 
          tabBarIcon: ({ color, size }) => (
            <Feather name="user" size={size} color={color} />
          )
        }} 
      />
    </Tabs>
  );
}
