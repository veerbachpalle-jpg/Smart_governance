import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from '../locales/en.json';
import hi from '../locales/hi.json';
import kn from '../locales/kn.json';

const SUPPORTED_LOCALES = ['en', 'hi', 'kn'] as const;
export type SupportedLocale = typeof SUPPORTED_LOCALES[number];

export function resolveInitialLocale(): SupportedLocale {
  if (typeof window === 'undefined') return 'en';
  try {
    // 1. Explicit user selection
    const saved = localStorage.getItem('civic-language');
    if (saved && SUPPORTED_LOCALES.includes(saved.toLowerCase() as SupportedLocale)) {
      return saved.toLowerCase() as SupportedLocale;
    }

    // 2. Account preference in stored session if available
    const sessionRaw = sessionStorage.getItem('civic-session');
    if (sessionRaw) {
      const sess = JSON.parse(sessionRaw);
      if (sess.preferredLanguage && SUPPORTED_LOCALES.includes(sess.preferredLanguage.toLowerCase())) {
        return sess.preferredLanguage.toLowerCase() as SupportedLocale;
      }
    }

    // 3. Browser languages list
    if (navigator.languages && navigator.languages.length > 0) {
      for (const lang of navigator.languages) {
        const code = lang.split('-')[0]?.toLowerCase();
        if (code && SUPPORTED_LOCALES.includes(code as SupportedLocale)) {
          return code as SupportedLocale;
        }
      }
    }

    // 4. Single browser language
    if (navigator.language) {
      const code = navigator.language.split('-')[0]?.toLowerCase();
      if (code && SUPPORTED_LOCALES.includes(code as SupportedLocale)) {
        return code as SupportedLocale;
      }
    }
  } catch {
    // fallback
  }
  return 'en';
}

const initialLang = resolveInitialLocale();

i18next.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    hi: { translation: hi },
    kn: { translation: kn },
  },
  lng: initialLang,
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18next;