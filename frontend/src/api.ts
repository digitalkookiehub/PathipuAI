import type {
  Book,
  Chapter,
  ChapterInput,
  ChapterPageText,
  ChaptersResponse,
  ExportItem,
  ExportRequest,
  GlossaryTerm,
  GlossaryTermInput,
  Language,
  NewBookInput,
  OcrEngine,
  OcrStatus,
  PageDetail,
  PageSummary,
  PublishStatus,
  SearchHit,
  TargetsResponse,
  TranslationChunk,
  TranslationOverview,
  TranslationStartResult,
} from './types'
import { CSRF_COOKIE, CSRF_HEADER, readCookie } from './csrf'

const BASE: string = import.meta.env.VITE_API_URL ?? ''
const FRIENDLY_FALLBACK = 'Something went wrong. Please try again.'
/** Fired when the server says this browser is no longer signed in. */
export const UNAUTHORIZED_EVENT = 'pathippu:unauthorized'
const SIGN_IN_PATHS = ['/auth/login', '/auth/setup']

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    const headers = new Headers(init?.headers)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method !== 'GET' && method !== 'HEAD') headers.set(CSRF_HEADER, readCookie(CSRF_COOKIE))
    response = await fetch(`${BASE}/api${path}`, { ...init, headers, credentials: 'same-origin' })
  } catch {
    throw new ApiError('Cannot reach the PathippuAI server. Is it running?', 0)
  }
  if (response.status === 401 && !SIGN_IN_PATHS.includes(path)) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!response.ok) {
    let message = FRIENDLY_FALLBACK
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // The server sent no JSON body; keep the friendly fallback.
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface AuthStatus {
  auth_required: boolean
  authenticated: boolean
  username: string | null
  is_admin: boolean
  setup_required: boolean
  /** whether "Forgot password" can email a link (email is set up on the server) */
  reset_available: boolean
}

export type AccountStatus = 'pending' | 'active' | 'disabled'

export interface Account {
  id: number
  username: string
  email: string | null
  is_admin: boolean
  status: AccountStatus
  created_at: string
}

export interface Registration {
  username: string
  email: string
  password: string
}

export const api = {
  authStatus: () => request<AuthStatus>('/auth/status'),
  login: (username: string, password: string) =>
    request<{ username: string }>('/auth/login', jsonInit('POST', { username, password })),
  setup: (username: string, password: string) =>
    request<{ username: string }>('/auth/setup', jsonInit('POST', { username, password })),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>(
      '/auth/change-password',
      jsonInit('POST', { current_password: currentPassword, new_password: newPassword }),
    ),
  register: (input: Registration) => request<{ message: string }>('/auth/register', jsonInit('POST', input)),
  forgotPassword: (email: string) =>
    request<{ message: string }>('/auth/forgot-password', jsonInit('POST', { email })),
  resetPassword: (token: string, newPassword: string) =>
    request<void>('/auth/reset-password', jsonInit('POST', { token, new_password: newPassword })),

  accounts: () => request<Account[]>('/admin/users'),
  approveAccount: (id: number) => request<Account>(`/admin/users/${id}/approve`, { method: 'POST' }),
  disableAccount: (id: number) => request<Account>(`/admin/users/${id}/disable`, { method: 'POST' }),
  setOwner: (id: number, isAdmin: boolean) =>
    request<Account>(`/admin/users/${id}/owner`, jsonInit('POST', { is_admin: isAdmin })),
  removeAccount: (id: number) => request<void>(`/admin/users/${id}`, { method: 'DELETE' }),

  languages: () => request<Language[]>('/languages'),
  books: () => request<Book[]>('/books'),
  book: (id: number) => request<Book>(`/books/${id}`),
  addBook: (input: NewBookInput) => {
    const form = new FormData()
    form.append('title', input.title)
    form.append('author', input.author)
    form.append('description', input.description)
    form.append('source_language', input.sourceLanguage)
    form.append('publication_details', input.publicationDetails)
    form.append('file', input.file)
    return request<Book>('/books', { method: 'POST', body: form })
  },
  deleteBook: (id: number) => request<void>(`/books/${id}?confirm=true`, { method: 'DELETE' }),

  ocrStatus: (id: number) => request<OcrStatus>(`/books/${id}/ocr`),
  startOcr: (id: number, firstPage: number | null, lastPage: number | null, retryFailed: boolean, engine: OcrEngine) =>
    request<{ status: string }>(
      `/books/${id}/ocr`,
      jsonInit('POST', { first_page: firstPage, last_page: lastPage, retry_failed: retryFailed, engine }),
    ),
  reread: (id: number, firstPage: number, lastPage: number, discardCorrections: boolean, engine: OcrEngine) =>
    request<{ status: string }>(
      `/books/${id}/ocr/reread`,
      jsonInit('POST', {
        first_page: firstPage,
        last_page: lastPage,
        discard_corrections: discardCorrections,
        engine,
      }),
    ),

  pages: (id: number) => request<PageSummary[]>(`/books/${id}/pages`),
  page: (id: number, pageNumber: number) => request<PageDetail>(`/books/${id}/pages/${pageNumber}`),
  saveText: (id: number, pageNumber: number, text: string) =>
    request<PageDetail>(`/books/${id}/pages/${pageNumber}/text`, jsonInit('PUT', { text })),
  approve: (id: number, pageNumber: number) =>
    request<PageDetail>(`/books/${id}/pages/${pageNumber}/approve`, { method: 'POST' }),
  restore: (id: number, pageNumber: number) =>
    request<PageDetail>(`/books/${id}/pages/${pageNumber}/restore`, { method: 'POST' }),
  search: (id: number, query: string) =>
    request<SearchHit[]>(`/books/${id}/search?q=${encodeURIComponent(query)}`),

  chapters: (id: number) => request<ChaptersResponse>(`/books/${id}/chapters`),
  addChapter: (id: number, input: ChapterInput) =>
    request<ChaptersResponse>(`/books/${id}/chapters`, jsonInit('POST', input)),
  updateChapter: (id: number, chapterId: number, input: Partial<ChapterInput>) =>
    request<ChaptersResponse>(`/books/${id}/chapters/${chapterId}`, jsonInit('PUT', input)),
  deleteChapter: (id: number, chapterId: number) =>
    request<ChaptersResponse>(`/books/${id}/chapters/${chapterId}`, { method: 'DELETE' }),
  reorderChapters: (id: number, chapters: Chapter[]) =>
    request<ChaptersResponse>(
      `/books/${id}/chapters/reorder`,
      jsonInit('POST', { chapter_ids: chapters.map((chapter) => chapter.id) }),
    ),
  chapterText: (id: number, chapterId: number) => request<ChapterPageText[]>(`/books/${id}/chapters/${chapterId}/text`),
  chapterExportUrl: (id: number, chapterId: number, approvedOnly: boolean) =>
    `${BASE}/api/books/${id}/chapters/${chapterId}/export?approved_only=${approvedOnly}`,

  glossary: (id: number) => request<GlossaryTerm[]>(`/books/${id}/glossary`),
  addTerm: (id: number, input: GlossaryTermInput) =>
    request<GlossaryTerm>(`/books/${id}/glossary`, jsonInit('POST', input)),
  updateTerm: (id: number, termId: number, input: GlossaryTermInput) =>
    request<GlossaryTerm>(`/books/${id}/glossary/${termId}`, jsonInit('PUT', input)),
  deleteTerm: (id: number, termId: number) => request<void>(`/books/${id}/glossary/${termId}`, { method: 'DELETE' }),

  approveMany: (id: number, firstPage: number, lastPage: number) =>
    request<{ approved: number; unread: number }>(
      `/books/${id}/pages/approve`,
      jsonInit('POST', { first_page: firstPage, last_page: lastPage }),
    ),

  targets: (id: number) => request<TargetsResponse>(`/books/${id}/targets`),
  setTargets: (id: number, languages: string[]) =>
    request<TargetsResponse>(`/books/${id}/targets`, jsonInit('PUT', { languages })),
  translation: (id: number) => request<TranslationOverview>(`/books/${id}/translation`),
  startTranslation: (id: number, chapterIds: number[] | null, languages: string[] | null, overwrite: boolean) =>
    request<TranslationStartResult>(
      `/books/${id}/translation`,
      jsonInit('POST', { chapter_ids: chapterIds, languages, overwrite }),
    ),
  translationChunks: (id: number, chapterId: number, language: string) =>
    request<TranslationChunk[]>(`/books/${id}/chapters/${chapterId}/translation/${language}`),

  editChunk: (id: number, chapterId: number, language: string, index: number, text: string) =>
    request<TranslationChunk>(
      `/books/${id}/chapters/${chapterId}/translation/${language}/${index}/text`,
      jsonInit('PUT', { text }),
    ),
  approveChunk: (id: number, chapterId: number, language: string, index: number) =>
    request<TranslationChunk>(`/books/${id}/chapters/${chapterId}/translation/${language}/${index}/approve`, {
      method: 'POST',
    }),
  restoreChunk: (id: number, chapterId: number, language: string, index: number) =>
    request<TranslationChunk>(`/books/${id}/chapters/${chapterId}/translation/${language}/${index}/restore`, {
      method: 'POST',
    }),
  approveAllChunks: (id: number, chapterId: number, language: string) =>
    request<{ approved: number; skipped: number }>(
      `/books/${id}/chapters/${chapterId}/translation/${language}/approve-all`,
      { method: 'POST' },
    ),

  publishing: (id: number) => request<PublishStatus>(`/books/${id}/publishing`),
  createExport: (id: number, body: ExportRequest) =>
    request<{ id: number }>(`/books/${id}/exports`, jsonInit('POST', body)),
  exports: (id: number) => request<ExportItem[]>(`/books/${id}/exports`),
  deleteExport: (id: number, exportId: number) => request<void>(`/books/${id}/exports/${exportId}`, { method: 'DELETE' }),
  exportFileUrl: (id: number, exportId: number, download: boolean) =>
    `${BASE}/api/books/${id}/exports/${exportId}/file?download=${download}`,

  lexicon: (id: number) => request<{ words: [string, number][] }>(`/books/${id}/lexicon`),

  pageImageUrl: (id: number, pageNumber: number, version: string) =>
    `${BASE}/api/books/${id}/pages/${pageNumber}/image?v=${encodeURIComponent(version)}`,
  exportUrl: (id: number, approvedOnly: boolean) => `${BASE}/api/books/${id}/export?approved_only=${approvedOnly}`,
}
