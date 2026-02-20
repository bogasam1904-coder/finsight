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
  return fetch(`${BASE_URL}/api${path}`, { ...options, headers });
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
