import { useEffect } from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { View, ActivityIndicator, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Analytics } from '@vercel/analytics/react';

// ✅ Part A: SEO/GEO tags injected on web only
if (Platform.OS === 'web' && typeof document !== 'undefined') {
  document.title = 'Finsight – AI-Powered Financial SEO Analytics | SEO';

  const setMeta = (name: string, content: string, isProperty = false) => {
    const attr = isProperty ? 'property' : 'name';
    let el = document.querySelector(`meta[${attr}="${name}"]`) as HTMLMetaElement;
    if (!el) { el = document.createElement('meta'); el.setAttribute(attr, name); document.head.appendChild(el); }
    el.setAttribute('content', content);
  };

  const addLink = (rel: string, href: string) => {
    let el = document.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement;
    if (!el) { el = document.createElement('link'); el.setAttribute('rel', rel); document.head.appendChild(el); }
    el.setAttribute('href', href);
  };

  const addScript = (id: string, json: object) => {
    if (document.getElementById(id)) return;
    const el = document.createElement('script');
    el.id = id; el.type = 'application/ld+json';
    el.textContent = JSON.stringify(json);
    document.head.appendChild(el);
  };

  setMeta('description', 'Discover data-driven SEO insights, keyword analysis, and performance dashboards with Finsight. Boost rankings with actionable AI-powered recommendations.');
  setMeta('robots', 'index, follow');
  addLink('canonical', 'https://finsight-vert.vercel.app/');
  setMeta('og:type', 'website', true);
  setMeta('og:url', 'https://finsight-vert.vercel.app/', true);
  setMeta('og:title', 'Finsight – AI-Powered Financial SEO Analytics', true);
  setMeta('og:description', 'Discover data-driven SEO insights, keyword analysis, and performance dashboards with Finsight. Boost rankings with actionable AI-powered recommendations.', true);
  setMeta('og:site_name', 'Finsight', true);
  setMeta('twitter:card', 'summary_large_image');
  setMeta('twitter:title', 'Finsight – AI-Powered Financial SEO Analytics');
  setMeta('twitter:description', 'Discover data-driven SEO insights, keyword analysis, and performance dashboards with Finsight.');

  addScript('schema-website', {
    '@context': 'https://schema.org', '@type': 'WebSite',
    'name': 'Finsight', 'url': 'https://finsight-vert.vercel.app/',
    'description': 'AI-powered financial SEO analytics platform.',
    'potentialAction': { '@type': 'SearchAction', 'target': 'https://finsight-vert.vercel.app/search?q={search_term_string}', 'query-input': 'required name=search_term_string' }
  });

  addScript('schema-org', {
    '@context': 'https://schema.org', '@type': 'Organization',
    'name': 'Finsight', 'url': 'https://finsight-vert.vercel.app/',
    'description': 'AI-powered financial SEO analytics platform helping businesses improve search rankings.',
    'foundingDate': '2024',
    'sameAs': ['https://github.com/bogasam1904-coder/finsight'],
    'contactPoint': { '@type': 'ContactPoint', 'contactType': 'customer support', 'url': 'https://finsight-vert.vercel.app/' }
  });

  addScript('schema-app', {
    '@context': 'https://schema.org', '@type': 'SoftwareApplication',
    'name': 'Finsight SEO Dashboard', 'applicationCategory': 'BusinessApplication',
    'operatingSystem': 'Web', 'url': 'https://finsight-vert.vercel.app/',
    'description': 'AI-powered dashboard that analyzes financial documents to deliver actionable SEO and GEO recommendations.',
    'offers': { '@type': 'Offer', 'price': '0', 'priceCurrency': 'USD' }
  });
}

function RootLayoutNav() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    if (loading) return;

    const inAuthGroup = segments[0] === '(auth)';
    const inTabsGroup = segments[0] === '(tabs)';

    if (user && inAuthGroup) { router.replace('/(tabs)'); return; }

    if (!user && inTabsGroup) {
      AsyncStorage.getItem('guest').then(isGuest => {
        if (!isGuest) router.replace('/(auth)/login');
      });
      return;
    }
  }, [user, loading, segments]);

  if (loading) return (
    <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#060B18' }}>
      <ActivityIndicator size="large" color="#4F8AFF" />
    </View>
  );

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="analysis/[id]" options={{ presentation: 'card' }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="light" />
      <Analytics />
      <RootLayoutNav />
    </AuthProvider>
  );
}
