/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `1` — все запросы /api отвечает MSW из src/mocks, бэкенд не нужен. */
  readonly VITE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
