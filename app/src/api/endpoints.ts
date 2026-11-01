import { api } from './client';

export type Major = { slug: string; name: string; color: string; is_coming_soon: boolean };
export type BookListItem = {
  slug: string;
  title: string;
  title_en: string;
  author: string;
  edition: string;
  motif: string;
  drawing: { viewBox: string; body: string } | null;
  cover: string | null;
  is_coming_soon: boolean;
  price: number | null;
  chapter_count: number;
  section_count: number;
  has_free_part: boolean;
  /** Number of the first free chapter, if a whole chapter is free. */
  free_chapter: number | null;
  owned: boolean;
  /** Why the whole book is open: bought, by subscription, or as a staff member. */
  access?: 'purchase' | 'gift' | 'subscription' | 'staff' | null;
  free_chapters?: number;
  all_free?: boolean;
  /** Only in the all-books list: the book's first major, for its cover. */
  major?: { slug: string; name: string; color: string } | null;
  /** Share of sections read (0–1), once the learner has started. */
  progress: number | null;
  /** «خبرم کن» is on. */
  notify: boolean;
  /** «خبرم کن» can be cancelled once; after asking again it stays on. */
  notify_can_cancel?: boolean;
};
export type NodeSummary = {
  id: number;
  slug: string;
  kind: 'book' | 'chapter' | 'section';
  title: string;
  is_locked: boolean;
  has_summary?: boolean;
  question_count?: number;
  flashcard_count?: number;
  group?: string;
};
export type ChapterSummary = NodeSummary & { sections: NodeSummary[]; has_overview?: boolean };
export type BookDetail = BookListItem & { about: string; majors: string[]; chapters: ChapterSummary[]; done_ids: number[] };
export type NodeDetail = {
  id: number;
  kind: NodeSummary['kind'];
  title: string;
  breadcrumb: { id: number; kind: NodeSummary['kind']; slug: string; title: string }[];
  summary: string;
  full: string;
  previous_id: number | null;
  next_id: number | null;
  previous_title?: string | null;
  next_title?: string | null;
};
export type Question = {
  id: number;
  stem: string;
  choices: { id: number; text: string }[];
  difficulty: 'easy' | 'medium' | 'hard';
  measured_difficulty?: number | null;
  domain?: 'general' | 'specialized' | '';
  kind?: 'recall' | 'concept' | 'calc' | 'analysis' | '';
  is_original: boolean;
  estimated_seconds: number | null;
  sources: { name: string; year: number; number: number | null }[];
};
export type AnswerResult = {
  is_correct: boolean;
  correct_choice_id: number;
  explanation: string;
  quick_solution: string;
  alternative_view: string;
  flashcards: { id: number; title: string }[];
};
export type Flashcard = { id: number; title: string; point: string; formula: string };
export type Banner = { id: number; title: string; subtitle: string; image: string | null; link: string };

export type User = { id: number; phone: string; email: string; first_name: string; last_name: string; is_staff?: boolean };
export type DeviceSessionInfo = { id: number; device_name: string; platform: string; created_at: string; last_seen_at: string; is_current: boolean };
export type VerifyResult = { token: string; session_id: number; user: User };
export type Note = { id: number; node_id: number; mode: 'full' | 'summary'; quote: string; body: string; color: string; created_at: string; updated_at: string };
export type NodeState = { bookmarked: boolean; percent: number; is_done: boolean; notes: Note[] };
export type PracticeState = { answered: Record<string, boolean>; reported: number[] };
export type Grade = 'again' | 'hard' | 'good' | 'easy';
export type GradeHints = Record<Grade, number>;
export type FlashcardState = {
  cards: Record<string, { box: number; due: boolean; hints: GradeHints }>;
  reported: number[];
  new_hints: GradeHints;
  mastered_box: number;
};
export type DueFlashcard = Flashcard & { box: number; hints: GradeHints };
export type AppReleaseInfo = { build: number; version_name: string; notes: string[]; download_url: string; required: boolean };
export type AppVersion = { status: 'ok' | 'optional' | 'required'; min_build: number; latest: AppReleaseInfo | null };
export type ExamQuestion = { id: number; stem: string; choices: { id: number; text: string }[]; difficulty: string };
export type ExamReview = {
  question_id: number;
  picked_choice_id: number | null;
  correct_choice_id: number | null;
  explanation: string;
  quick_solution: string;
  alternative_view: string;
};
export type ExamSummary = {
  id: number;
  node_id: number;
  node_title: string;
  question_count: number;
  negative_marking: boolean;
  time_limit_seconds: number;
  started_at: string;
  ends_at: string;
  submitted_at: string | null;
  correct: number;
  wrong: number;
  blank: number;
  score_percent: number | null;
};
export type ExamPage = {
  results: (ExamSummary & { book_title: string })[];
  has_more: boolean;
  summary: { count: number; average: number | null; best: number | null; trend: number[] };
  books: { slug: string; title: string }[];
};
export type ExamDetail = ExamSummary & { questions: ExamQuestion[]; review?: ExamReview[] };
export type Library = {
  reading: { book_slug: string; book_title: string; last_section: { id: number; title: string }; updated_at: string }[];
  bookmarks: { id: number; title: string; created_at: string }[];
  notes: (Note & { node_title: string })[];
};
export type Stats = {
  sections_done: number;
  answers: number;
  accuracy: number | null;
  cards_reviewed: number;
  cards_mastered: number;
  exams: number;
  streak_days: number;
  study_days: number;
  last_14_days: { date: string; sections: number; answers: number; cards: number }[];
  books: { slug: string; title: string; done: number; total: number }[];
  weak_sections: { id: number; title: string; answers: number; accuracy: number }[];
};
export type Plan = { id: number; title: string; scope: 'major' | 'all'; months: number; price: number };
export type Offers = { book: { slug: string; title: string; price: number | null }; majors: { slug: string; name: string }[]; plans: Plan[] };
export type OrderStatus = { id: number; title: string; amount: number; status: 'pending' | 'paid' | 'failed'; ref_number: string; book_slug: string | null };
export type Purchases = {
  active: { id: number; kind: 'book' | 'subscription'; title: string; book_slug: string | null; major_slug: string | null; starts_at: string; ends_at: string | null }[];
  orders: { id: number; title: string; amount: number; paid_at: string; ref_number: string }[];
};
export type OfflineBundle = {
  book: { slug: string; title: string };
  sections: { id: number; title: string; summary: string; full: string }[];
  downloaded_at: string;
  valid_until: string;
};
export type ReportReason = 'wrong_answer' | 'formula' | 'unclear' | 'typo' | 'other';

export const endpoints = {
  majors: () => api<Major[]>('majors/'),
  books: (major: string) => api<BookListItem[]>(`majors/${encodeURIComponent(major)}/books/`),
  allBooks: () => api<BookListItem[]>('books/'),
  book: (slug: string) => api<BookDetail>(`books/${encodeURIComponent(slug)}/`),
  node: (id: number) => api<NodeDetail>(`nodes/${id}/`),
  notifyBook: (slug: string, on: boolean) => api<{ notify: boolean; can_cancel: boolean }>(`books/${encodeURIComponent(slug)}/notify/`, { body: { on } }),
  glossary: (slug: string) => api<{ book: string; terms: { fa: string; en: string; meaning: string; section_id: number; section_title: string }[] }>(`books/${encodeURIComponent(slug)}/glossary/`),
  questions: (nodeId: number) => api<{ questions: Question[]; locked_count: number }>(`nodes/${nodeId}/questions/`),
  answer: (questionId: number, choiceId: number) => api<AnswerResult>(`questions/${questionId}/answer/`, { body: { choice_id: choiceId } }),
  flashcards: (nodeId: number) => api<{ flashcards: Flashcard[]; locked_count: number }>(`nodes/${nodeId}/flashcards/`),
  banners: (major: string) => api<Banner[]>(`banners/?major=${encodeURIComponent(major)}`),
  bannerClick: (id: number) => api<{ ok: boolean }>(`banners/${id}/click/`, { method: 'POST' }),
  health: (baseUrl?: string) => api<{ status: string }>('health/', { baseUrl }),

  // Account
  requestOtp: (phone: string, appHash?: string) => api<{ sent: boolean; expires_in: number }>('auth/request-otp/', { body: { phone, app_hash: appHash }, timeoutMs: 25_000 }),
  verifyOtp: (body: { phone: string; code: string; device_name: string; platform: string; replace_session_id?: number }) =>
    api<VerifyResult>('auth/verify-otp/', { body }),
  logout: () => api<{ logged_out: boolean }>('auth/logout/', { method: 'POST' }),
  me: () => api<User>('me/'),
  updateMe: (body: Partial<Pick<User, 'first_name' | 'last_name' | 'email'>>) => api<User>('me/', { method: 'PATCH', body }),
  sessions: () => api<DeviceSessionInfo[]>('me/sessions/'),
  revokeSession: (id: number) => api<{ revoked: boolean }>(`me/sessions/${id}/revoke/`, { method: 'POST' }),

  // The learner's data
  nodeState: (id: number) => api<NodeState>(`nodes/${id}/me/`),
  saveProgress: (id: number, percent: number, done = false) => api<{ percent: number; is_done: boolean }>(`nodes/${id}/progress/`, { body: { percent, done } }),
  toggleBookmark: (id: number) => api<{ bookmarked: boolean }>(`nodes/${id}/bookmark/`, { method: 'POST' }),
  addNote: (id: number, body: { quote?: string; body?: string; color?: string; mode?: string }) => api<Note>(`nodes/${id}/notes/`, { body }),
  editNote: (id: number, body: { body?: string; color?: string }) => api<Note>(`notes/${id}/`, { method: 'PATCH', body }),
  deleteNote: (id: number) => api<{ deleted: boolean }>(`notes/${id}/`, { method: 'DELETE' }),
  practiceState: (id: number) => api<PracticeState>(`nodes/${id}/practice/`),
  practiceReset: (id: number) => api<{ reset: number }>(`nodes/${id}/practice/reset/`, { method: 'POST' }),
  flashcardState: (id: number) => api<FlashcardState>(`nodes/${id}/flashcards/me/`),
  reviewFlashcard: (id: number, grade: Grade) => api<{ box: number; mastered: boolean }>(`flashcards/${id}/review/`, { body: { grade } }),
  dueFlashcards: () => api<{ count: number; flashcards: DueFlashcard[] }>('me/flashcards/due/'),
  reportQuestion: (id: number, reason: ReportReason, note: string) => api<{ reported: boolean }>(`questions/${id}/report/`, { body: { reason, note } }),
  reportFlashcard: (id: number, reason: ReportReason, note: string) => api<{ reported: boolean }>(`flashcards/${id}/report/`, { body: { reason, note } }),
  reportNode: (id: number, reason: ReportReason, note: string) => api<{ reported: boolean }>(`nodes/${id}/report/`, { body: { reason, note } }),
  startExam: (nodeId: number, body: { count: number; negative_marking: boolean; minutes?: number }) => api<ExamDetail>(`nodes/${nodeId}/exams/`, { body }),
  exam: (id: number) => api<ExamDetail>(`exams/${id}/`),
  submitExam: (id: number, answers: Record<string, number | null>) => api<ExamDetail>(`exams/${id}/submit/`, { body: { answers } }),
  myExams: () => api<ExamSummary[]>('me/exams/'),
  examPage: (page: number, book = '') => api<ExamPage>(`me/exams/?page=${page}${book ? `&book=${encodeURIComponent(book)}` : ''}`),
  library: () => api<Library>('me/library/'),
  appVersion: (platform: string, build: number) => api<AppVersion>(`app/version/?platform=${platform}&build=${build}`),
  stats: () => api<Stats>('me/stats/'),
  offline: (slug: string) => api<OfflineBundle>(`books/${encodeURIComponent(slug)}/offline/`, { timeoutMs: 90_000 }),

  // Sales (prices always come from the server)
  offers: (book: string) => api<Offers>(`offers/?book=${encodeURIComponent(book)}`),
  createOrder: (body: { book?: string; plan?: number; major?: string }) => api<{ order_id: number; amount: number; pay_url: string }>('orders/', { body, timeoutMs: 30_000 }),
  order: (id: number, check = false) => api<OrderStatus>(`orders/${id}/${check ? '?check=1' : ''}`, { timeoutMs: 30_000 }),
  purchases: () => api<Purchases>('me/purchases/'),
};
