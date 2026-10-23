export interface Language {
  code: string
  name: string
}

export interface Book {
  id: number
  title: string
  author: string
  description: string
  source_language: string
  source_language_name: string
  publication_details: string
  page_count: number
  status: string
  status_label: string
  created_at: string
}

export type ReviewStatus = 'pending' | 'corrected' | 'approved'

export interface PageSummary {
  page_number: number
  ocr_status: string
  review_status: ReviewStatus
  ocr_confidence: number | null
}

export interface PageDetail extends PageSummary {
  ocr_text: string
  corrected_text: string | null
  text: string
  error: string | null
  has_image: boolean
  ocr_engine: string | null
}

export interface SearchHit {
  page_number: number
  snippet: string
}

export interface OcrJob {
  status: string
  total: number
  completed: number
  failed: number
}

export type OcrEngine = 'tesseract' | 'careful'

export interface EngineAccuracy {
  pages: number
  error_rate: number | null
}

export interface OcrAccuracy {
  pages: number
  error_rate: number | null
  by_engine: Record<string, EngineAccuracy>
}

export interface EngineStatus {
  ready: boolean
  message: string | null
}

export interface OcrStatus {
  running: boolean
  error: string | null
  ready: boolean
  ready_message: string | null
  page_counts: Record<string, number>
  review_counts: Record<ReviewStatus, number>
  job: OcrJob | null
  accuracy: OcrAccuracy
  engines: Record<OcrEngine, EngineStatus>
}

export interface NewBookInput {
  title: string
  author: string
  description: string
  sourceLanguage: string
  publicationDetails: string
  file: File
}

export interface Chapter {
  id: number
  title: string
  heading: string
  order_index: number
  start_page: number
  end_page: number
  page_count: number
  read_pages: number
  approved_pages: number
}

export interface ChaptersResponse {
  chapters: Chapter[]
  unassigned: [number, number][]
}

export interface ChapterInput {
  title: string
  heading: string
  start_page: number
  end_page: number
}

export interface ChapterPageText {
  page_number: number
  review_status: ReviewStatus
  text: string
}

export interface GlossaryTerm {
  id: number
  source_term: string
  explanation: string
  author_notes: string
  keep_unchanged: boolean
  translations: Record<string, string>
}

export type GlossaryTermInput = Omit<GlossaryTerm, 'id'>

export interface TargetsResponse {
  selected: string[]
  available: Language[]
}

export interface TranslationProvider {
  name: string
  label: string
  ready: boolean
  message: string | null
  is_test: boolean
  model: string | null
}

export type TranslationStatus = 'not_started' | 'in_progress' | 'awaiting_approval' | 'approved' | 'failed'

export interface LanguageProgress {
  status: TranslationStatus
  total: number
  translated: number
  approved: number
  failed: number
  notes: number
  outdated: boolean
  test_output: boolean
  untranslated: number
  error: string | null
}

export interface ChapterProgress {
  id: number
  title: string
  order_index: number
  page_count: number
  approved_pages: number
  ready: boolean
  missing_pages: number[]
  languages: Record<string, LanguageProgress>
}

export interface TranslationJob {
  status: string
  total: number
  completed: number
  failed: number
  error: string | null
}

export interface TranslationOverview {
  provider: TranslationProvider
  running: boolean
  error: string | null
  job: TranslationJob | null
  targets: string[]
  chapters: ChapterProgress[]
}

export interface TranslationStartResult {
  status: 'started' | 'nothing_to_do'
  chunks: number
  skipped: { id: number; title: string; missing_pages: number[] }[]
}

export interface TranslationChunk {
  chunk_index: number
  source_text: string
  translated_text: string | null
  edited_text: string | null
  status: string
  notes: string | null
  error: string | null
  provider: string | null
  outdated: boolean
  untranslated: boolean
}

export type ExportKind = 'source' | 'target' | 'bilingual' | 'multilingual'

export interface ReadyInfo {
  ready: boolean
  problems: string[]
}

export interface PublishStatus {
  chapters: number
  unassigned: [number, number][]
  targets: string[]
  source: ReadyInfo
  languages: Record<string, ReadyInfo>
  running: boolean
}

export interface ExportRequest {
  kind: ExportKind
  languages: string[]
  toc: boolean
  page_references: boolean
  sample: boolean
  numbered_paragraphs: boolean
}

export interface ExportItem {
  id: number
  kind: ExportKind
  languages: string[]
  status: 'processing' | 'done' | 'failed'
  file_name: string | null
  size_bytes: number | null
  page_count: number | null
  toc: boolean
  page_references: boolean
  sample: boolean
  numbered_paragraphs: boolean
  error: string | null
  created_at: string
}
