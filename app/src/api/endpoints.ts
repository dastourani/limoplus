import type { Label } from '../lib/labels';
import type { Numbering, RefTarget } from '../lib/numbering';
import { api } from './client';
import type { ReadingNext } from '../components/home/ReadingCards';
import type { ChapterEnd, ChapterIntro, SectionStatus } from '../lib/renderMarkdown';

export type Major = { slug: string; name: string; color: string; is_coming_soon: boolean };
export type PriceDiscount = { amount: number; percent: number; starts_at: string; ends_at: string; campaign_title: string };
export type ProductStatus = {
  /** Server-owned product state; never derive it from a null price, `all_free`, or a chapter flag. */
  state: 'unavailable' | 'coming_soon' | 'free' | 'preparing' | 'unpriced' | 'paid';
  /** A free chapter/section is a preview, not a free whole book. */
  preview: 'none' | 'sample';
  /** Whether the current server quote is under an active discount campaign. */
  promotion: 'none' | 'discount';
};
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
  release_estimate?: string;
  product_status: ProductStatus;
  /** Effective price at the time the API response was generated. */
  price: number | null;
  /** Regular list price, kept separately so a client can stop showing a stale campaign after it expires. */
  regular_price: number | null;
  discount: PriceDiscount | null;
  chapter_count: number;
  section_count: number;
  /** Number of the first free chapter, if a whole chapter is free; product_status.preview decides whether to show it. */
  free_chapter: number | null;
  owned: boolean;
  /** Why the whole book is open: bought, by subscription, or as a staff member. */
  access?: 'purchase' | 'gift' | 'subscription' | 'staff' | null;
  free_chapters?: number;
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
  /** «به‌روز شده»: marked in the panel since the learner last read it. */
  badge?: Badge;
};
/** A chapter in the book page's tree. `question_count` and `flashcard_count` are its sections' totals, summed by the
 * server: the chapter's «N تست» line and its «تمرین کل فصل» / «آزمون» / «فلش‌کارت» buttons follow them. */
export type ChapterSummary = NodeSummary & { sections: NodeSummary[]; has_overview?: boolean; term_count?: number };
export type Shelf = { id: number | null; title: string; books: BookListItem[] };
export type BookDetail = BookListItem & {
  id: number;
  /** Flashcards of the learner's finished (green) sections: «مرور فلش‌کارت‌های کتاب». */
  done_card_count: number;
  about: string;
  majors: string[];
  chapters: ChapterSummary[];
  /** «تمام شد»: read, and enough of the section's questions answered (green tick). */
  done_ids: number[];
  /** «خوانده شد»: read to the end, questions still to do (half lemon). */
  read_ids?: number[];
  /** Signed-in learners: «اشتباه‌هایم در این کتاب» and «آزمون‌هایم از این کتاب». */
  mine?: {
    mistakes: { count: number; open: number; settling: number; due: number };
    exams: number;
    /** «زمان مطالعه»: exact seconds in this book, and per chapter id. */
    time_seconds?: number;
    chapter_seconds?: Record<string, number>;
  } | null;
  /** «N از M لغت»: word cards (w-…) learned (Leitner box 4+) out of the book's word cards; null without word cards. */
  words?: { learned: number; total: number } | null;
  /** Shareable questions of this book the learner can see («تست‌های نمونه»). */
  sample_count?: number;
  /** Sent with «معرفی به دوست»: the book's own link, or the default one set in the panel (empty: none). */
  share_link?: string;
  /** Each finished chapter's next review, and the book's weekly mixed review. */
  reviews?: { chapters: Record<string, { id?: number; step: number; due_on: string; days: number; done: number }>; book: { due_on: string; days: number } | null } | null;
  /** «آخرین به‌روزرسانی»: the date of the book's last «مطلب تازه», and how many lines «تغییرات کتاب» has. */
  updated_on?: string | null;
  change_count?: number;
  author_profile?: {
    name: string;
    academic_title: string;
    avatar: string | null;
    bio: string;
    contact_email?: string;
    social_links?: string;
  };
  community_reviews?: {
    average_rating: number;
    satisfaction_rate: number;
    serious_readers_rating: number;
    total_count: number;
    reviews: {
      id: number;
      display_name: string;
      rating: number;
      satisfaction_percent: number;
      body: string;
      study_percent: number;
      test_percent: number;
      is_pinned: boolean;
      teacher_reply?: string;
      created_at: string;
    }[];
  };
};
export type NodeDetail = {
  id: number;
  /** The panel's labels («برچسب‌ها»): boxes in the notes and parts of the summary. */
  labels?: Label[];
  /** «مثال ۳-۵»: where this section's count starts, and the book's [[#names]]. */
  numbering?: Numbering | null;
  kind: NodeSummary['kind'];
  title: string;
  breadcrumb: { id: number; kind: NodeSummary['kind']; slug: string; title: string; number?: number | null }[];
  summary: string;
  full: string;
  previous_id: number | null;
  next_id: number | null;
  previous_title?: string | null;
  next_title?: string | null;
  /** The last section of a chapter: its summary exam and the next chapter (null at the end of the book). */
  chapter_end?: ChapterEnd | null;
  /** Signed-in learners: what is left in this section. */
  status?: SectionStatus | null;
  /** A chapter's own page is its introduction: its sections and where to go on. */
  intro?: ChapterIntro | null;
  badge?: Badge;
  /** «دستورهای فرمول» for KaTeX. */
  macros?: Record<string, string>;
  /** What there is to practise here: a section its own, a chapter its sections'. The buttons that lead to a
   * practice screen are hidden when the count is 0 (a book with no tests never offers «تست‌ها»). */
  question_count?: number;
  flashcard_count?: number;
};
/** «تغییرات کتاب»: the important updates of a book, newest first. */
export type BookChanges = { title: string; changes: { id: number; text: string; at: string; place: string; node_id: number | null }[] };
/** «تازه» (added since the learner started the section) or «به‌روز شده» (marked in the panel since they saw it). */
export type Badge = 'new' | 'updated' | null;
export type Question = {
  id: number;
  /** The section the question belongs to («این نکته در جزوه»), and its title (shown above «سؤال ۱ از ۴»). */
  node_id?: number;
  node_title?: string;
  /** Its chapter's number: «فصل ۱، نام بخش». */
  chapter_number?: number | null;
  /** One of the book's few sample questions that may be shared as an image. */
  shareable?: boolean;
  /** For the shared picture: the book and chapter it comes from. */
  share_place?: { book: string; chapter: string; chapter_number: number | null } | null;
  stem: string;
  choices: { id: number; text: string }[];
  difficulty: 'easy' | 'medium' | 'hard';
  measured_difficulty?: number | null;
  domain?: 'general' | 'specialized' | '';
  kind?: 'recall' | 'concept' | 'calc' | 'analysis' | '';
  is_original: boolean;
  estimated_seconds: number | null;
  sources: { name: string; year: number; number: number | null }[];
  /** Shown as written: shuffling would change what a choice like «گزینه‌های ۱ و ۳» means. */
  fixed_order?: boolean;
  /** «تست تکمیلی»: extra practice after the section's own tests; not counted in its progress. */
  extra?: boolean;
  /** The answer key was corrected («اصلاح‌شده»). */
  corrected?: Correction | null;
  badge?: Badge;
};
export type Correction = { at: string; note: string };
/** One box of «کادرهای کتاب»: all boxes of one label, in reading order. */
export type BoxItem = { label: string; title: string; name: string; body: string; section_id: number; section_title: string; chapter_number: number | null };
export type Solution = { title: string; body: string };
/** «کنکورهای سال‌های قبل» of a book: each exam with its tests here (a test in several exams counts in each). */
export type PastExams = {
  /** ready: the share (0–100) of its tests from chapters the learner has studied (null for guests). */
  exams: { id: number; name: string; year: number; count: number; minutes: number; ready?: number | null }[];
  years: number[];
  /** «تکراری‌ها و مشابه‌ها»: each konkur (by name, every year) and its groups of repeated or similar tests. */
  names?: { name: string; repeats: number }[];
  repeats?: number;
  total: number;
  locked: number;
};
export type AnswerResult = {
  is_correct: boolean;
  correct_choice_id: number;
  explanation: string;
  /** Extra solutions, each under the title the panel gave it. */
  solutions?: Solution[];
  flashcards: { id: number; title: string }[];
  /** «مشابه»: the same test with a change in another exam. */
  similar?: { id: number; node_id: number; source: string }[];
  /** The book the linked cards belong to (opened with flashcards(book_id, …, ids)). */
  book_id?: number;
  /** Linked cards just added to today's review after a wrong answer. */
  cards_queued?: number;
  node_id?: number;
  /** A question from the mistakes notebook answered right: what it did («settling»: comes back in due_in days;
   * «settled»: left the notebook; «early»: settling and not its day yet). days = since it went wrong. */
  fixed?: { step: 'settling' | 'settled' | 'early'; days: number; due_in?: number } | null;
  corrected?: (Correction & { answered_before: boolean }) | null;
};
export type MistakeItem = {
  question_id: number;
  text: string;
  node_id: number;
  node_title: string;
  book_slug: string;
  book_title: string;
  wrong_count: number;
  blank: boolean;
  source: 'practice' | 'exam';
  last_at: string;
  reason: string;
  /** The answer key changed after this learner's last answer. */
  corrected?: boolean;
  state: 'open' | 'settling';
  /** Settling: the day it comes back. */
  due_on: string | null;
  is_due: boolean;
  /** «کمبود وقت»: the question's time and the titles of its other solutions. */
  seconds?: number | null;
  solutions?: string[];
};
/** «حساب من» › «راهنما» and «قوانین» (panel: «صفحه‌های راهنما»، «صفحه‌های سایت»). */
export type SitePageItem = { slug: string; title: string; updated_at: string; important_at: string | null };
export type SitePageDetail = SitePageItem & { body: string };
export type AppPages = { help: { id: number; title: string }[]; pages: SitePageItem[] };
export type Today = {
  away_days: number;
  /** Back after a few days away: a short start instead of everything that piled up. */
  comeback: boolean;
  cards: number;
  cards_total: number;
  mistakes: number;
  practise: number;
  continue: { id: number; title: string; book_title: string; book_slug: string } | null;
  minutes: number;
  /** Chapter and book reviews due today (at most two), and how many more wait. */
  reviews?: ReviewItem[];
  reviews_waiting?: number;
  /** «برنامه‌ی امروز» tiles, in order; a job done today is gone. */
  tasks?: TodayTask[];
  /** «نیاز به مرور»: sections with wrong answers still open, or finished long ago (at most three). */
  needs_review?: { items: NeedsReviewItem[]; total: number };
  /** Study seconds in the last 7 days and the 7 before (the greeting's line). */
  week?: { seconds: number; before: number };
};
export type NeedsReviewItem = { id: number; title: string; book_title: string; book_slug: string; reason: 'mistakes' | 'old'; mistakes: number; days: number; question_ids?: number[] };
export type TodayTask =
  | (Omit<ReviewItem, 'kind'> & { kind: 'review'; review_kind: 'chapter' | 'book'; done?: number })
  | { kind: 'cards'; count: number; total: number; comeback: boolean; minutes: number; done?: number }
  | { kind: 'notebook'; count: number; total: number; minutes: number; done?: number };
/** A review whose day has come: «مرور فصل ۲ «…» از …: ۵ تست، حدود ۷ دقیقه». */
export type ReviewItem = {
  kind: 'chapter' | 'book';
  id: number;
  book_slug: string;
  book_title: string;
  chapter_id: number | null;
  chapter_title: string;
  chapter_number: number | null;
  chapters?: number;
  step: number | null;
  is_exam: boolean;
  questions: number;
  minutes: number;
  due_on: string;
  late_days: number;
};
export type ReviewSessionData = {
  id: number;
  kind: 'chapter' | 'book';
  title: string;
  book_title: string;
  minimum: number;
  answered: number;
  right: number;
  more: boolean;
  finished: boolean;
  exam_id: number | null;
  questions: Question[];
  next_due_on?: string | null;
  next_in_days?: number;
};
export type SearchResult = {
  kind: 'section' | 'question' | 'flashcard' | 'note';
  id: number;
  node_id: number;
  title: string;
  book_title: string;
  book_slug: string;
  snippet: string;
  match: string;
  mode?: 'full' | 'summary';
};
export type Mistakes = {
  count: number;
  /** «منتظر جبران»: the latest answer was wrong. */
  open: number;
  /** «نیازمند تثبیت»: right once since, waiting for a right answer on a later day. */
  settling: number;
  /** Open, plus settling ones whose day has come: what «تمرین» asks. */
  due: number;
  settle_days: number;
  items: MistakeItem[];
  books: { slug: string; title: string }[];
  reasons: { key: string; label: string }[];
};
/** node_title: the section the card belongs to (shown above «کارت ۲ از ۸»). */
export type Flashcard = {
  id: number;
  title: string;
  point: string;
  formula: string;
  node_id?: number;
  node_title?: string;
  chapter_number?: number | null;
  /** «تست‌های این نکته»: tests linked to the card. */
  question_ids?: number[];
  badge?: Badge;
};
export type Banner = {
  id: number;
  title: string;
  subtitle: string;
  image: string | null;
  link: string;
  template?: 'lemon' | 'sale' | 'book' | 'exam';
  button?: string;
  motif?: string;
  /** Set for a generic banner countdown or the linked campaign's end time. */
  ends_at?: string | null;
  server_now?: string;
  /** Prices and product come from the linked campaign, never from copy typed into the banner. */
  discount?: {
    kind: 'book' | 'plan';
    product_title: string;
    months: number | null;
    regular_price: number;
    price: number;
    amount: number;
    percent: number;
    campaign_title: string;
    starts_at: string;
    ends_at: string;
  } | null;
  book?: (import('../components/BookCover').CoverBook & { major: { name: string; color: string } | null }) | null;
};

export type User = { id: number; phone: string; email: string; first_name: string; last_name: string; is_staff?: boolean };
export type DeviceSessionInfo = { id: number; device_name: string; platform: string; created_at: string; last_seen_at: string; is_current: boolean };
export type VerifyResult = { token: string; session_id: number; user: User };
export type Note = { id: number; node_id: number; mode: 'full' | 'summary'; quote: string; body: string; color: string; created_at: string; updated_at: string };
export type NodeState = {
  bookmarked: boolean;
  percent: number;
  is_done: boolean;
  notes: Note[];
  /** The reader's current place (0–100) and mode, from whichever device they read on last. */
  position?: number;
  mode?: 'full' | 'summary';
  at?: string | null;
};
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
export type ExamQuestion = { id: number; stem: string; choices: { id: number; text: string }[]; difficulty: string; fixed_order?: boolean };
export type ExamReview = {
  question_id: number;
  picked_choice_id: number | null;
  correct_choice_id: number | null;
  explanation: string;
  solutions?: Solution[];
  node_id?: number | null;
  /** The answer key was corrected after this exam began (the score keeps the key it was taken with). */
  corrected?: Correction | null;
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
  /** «تمرکز روی اشتباه‌هایم»: how many questions came from the learner's mistakes. */
  focused?: number;
  /** The previous finished exam on the same chapter (for «نسبت به دفعه‌ی قبل بهتر شدی»). */
  previous_score?: number | null;
};
export type ExamPage = {
  /** number: the exam's place among the learner's exams on the same chapter («آزمون ۳»). */
  results: (ExamSummary & { book_title: string; number?: number | null })[];
  has_more: boolean;
  summary: { count: number; average: number | null; best: number | null; trend: number[] };
  books: { slug: string; title: string }[];
};
/** An exam's results for one chapter («کارنامه به تفکیک فصل»). */
export type ChapterResult = { chapter_id: number; title: string; total: number; right: number; wrong: number; blank: number; percent: number; weakest: boolean };
export type ExamDetail = ExamSummary & { questions: ExamQuestion[]; review?: ExamReview[]; by_chapter?: ChapterResult[] };
export type LibraryShelfStatus = 'reading' | 'later' | 'finished';
export type LibraryBook = {
  book_id: number;
  status: LibraryShelfStatus;
  hidden: boolean;
  position: number;
  book: BookListItem;
};
export type Library = {
  /** Every currently accessible full book: free, bought, subscribed, or privately granted. */
  books?: LibraryBook[];
  reading: {
    book_slug: string;
    book_title: string;
    last_section: { id: number; title: string };
    /** The section's chapter: «فصل ۳: مشتق» on the continue card. */
    chapter?: { number: number | null; title: string } | null;
    percent?: number;
    updated_at: string;
    book?: BookListItem;
    /** The section was finished: where «ادامه بده» goes (the next chapter at a chapter's end). */
    next?: ReadingNext | null;
  }[];
  bookmarks: { id: number; title: string; created_at: string }[];
  notes: (Note & { node_title: string })[];
  mistakes?: { count: number; open: number; settling: number; due: number };
};
export type Stats = {
  sections_done: number;
  answers: number;
  accuracy: number | null;
  cards_reviewed: number;
  cards_mastered: number;
  /** «N از M لغت» per book whose word cards the learner has started. */
  words?: { slug: string; title: string; learned: number; total: number }[];
  exams: number;
  streak_days: number;
  study_days: number;
  last_14_days: { date: string; sections: number; answers: number; cards: number }[];
  /** «روزهای مطالعه»: the last 53 weeks, only days with something done. */
  year?: {
    since: string;
    days: { date: string; sections: number; answers: number; correct?: number; cards: number; exams?: number; seconds: number }[];
    longest_streak: number;
    /** Where the longest run of days lies (null when it is a single day). */
    longest_from?: string | null;
    longest_to?: string | null;
  };
  books: { slug: string; title: string; done: number; total: number }[];
  weak_sections: { id: number; title: string; answers: number; accuracy: number }[];
  /** Of the questions got wrong in the last `days` days: answered right later, and settled. */
  improvement?: { days: number; wrong: number; fixed: number; settled: number };
  /** The stats page's cards: finish dates at the recent pace, and the best time of day for tests. */
  insights?: {
    forecast: { slug: string; title: string; left: number; days: number; finish_on: string }[];
    best_hours: { from: number; to: number; share: number } | null;
  };
  /** «زمان مطالعه» in exact seconds (rounded only when shown). */
  time?: StudyTimeTotals;
};
export type StudyKindName = 'read' | 'quiz' | 'cards' | 'exam' | 'review';
export type StudyTimeTotals = {
  seconds: number;
  week_seconds: number;
  by_kind: Partial<Record<StudyKindName, number>>;
  last_14_days: { date: string; seconds: number }[];
};
export type Plan = {
  id: number;
  title: string;
  scope: 'major' | 'all';
  months: number;
  /** Total payable for the whole term, after any active campaign. */
  price: number;
  regular_price: number;
  discount: PriceDiscount | null;
  product_status: ProductStatus;
};
export type Offers = {
  book: {
    slug: string;
    title: string;
    price: number | null;
    regular_price: number | null;
    discount: PriceDiscount | null;
    product_status: ProductStatus;
  };
  majors: { slug: string; name: string }[];
  plans: Plan[];
  payments_enabled: boolean;
};
export type OrderStatus = {
  id: number;
  title: string;
  amount: number;
  regular_amount: number;
  discount_amount: number;
  campaign_title: string;
  status: 'pending' | 'paid' | 'failed';
  ref_number: string;
  book_slug: string | null;
};
export type Purchases = {
  active: { id: number; kind: 'book' | 'subscription'; title: string; book_slug: string | null; major_slug: string | null; starts_at: string; ends_at: string | null }[];
  orders: { id: number; title: string; amount: number; regular_amount: number; discount_amount: number; campaign_title: string; paid_at: string; ref_number: string }[];
};
export type OfflineBundle = {
  book: { slug: string; title: string };
  sections: { id: number; title: string; summary: string; full: string }[];
  downloaded_at: string;
  valid_until: string;
};
export type ReportReason = 'wrong_answer' | 'explanation' | 'formula' | 'unclear' | 'typo' | 'translation' | 'image' | 'other';
/** Where a report on the lesson text points: the selected words, notes or summary, and the box. */
export type ReportPlace = { quote?: string; mode?: 'full' | 'summary'; box?: string };

export const endpoints = {
  majors: () => api<Major[]>('majors/'),
  books: (major: string) => api<BookListItem[]>(`majors/${encodeURIComponent(major)}/books/`),
  allBooks: () => api<BookListItem[]>('books/'),
  /** The home page rows: each shelf set in the panel, then «کتاب‌های دیگر». */
  shelves: () => api<Shelf[]>('shelves/'),
  book: (slug: string) => api<BookDetail>(`books/${encodeURIComponent(slug)}/`),
  node: (id: number) => api<NodeDetail>(`nodes/${id}/`),
  notifyBook: (slug: string, on: boolean) => api<{ notify: boolean; can_cancel: boolean }>(`books/${encodeURIComponent(slug)}/notify/`, { body: { on } }),
  submitReview: (slug: string, data: { rating: number; satisfaction_percent: number; body: string }) =>
    api<{ status: string; message: string; review_id: number }>(`books/${encodeURIComponent(slug)}/reviews/`, { body: data }),
  knownWords: (slug: string) => api<{ known: string[] }>(`books/${encodeURIComponent(slug)}/words/me/`),
  markWords: (slug: string, terms: string[], known: boolean) =>
    api<{ known: string[] }>(`books/${encodeURIComponent(slug)}/words/me/`, { body: { terms, known } }),
  glossary: (slug: string, chapter?: string) =>
    api<{ book: string; chapter?: string | null; terms: { fa: string; en: string; meaning: string; section_id: number; section_title: string }[] }>(
      `books/${encodeURIComponent(slug)}/glossary/${chapter ? `?chapter=${encodeURIComponent(chapter)}` : ''}`,
    ),
  boxes: (nodeId: number, label?: string) =>
    api<{ labels: { name: string; style: string; count: number }[]; boxes: BoxItem[]; locked_count: number; title: string; all_labels: Label[]; refs: Record<string, RefTarget> }>(
      `nodes/${nodeId}/boxes/${label ? `?label=${encodeURIComponent(label)}` : ''}`,
    ),
  questions: (nodeId: number, ids?: string) => api<{ questions: Question[]; locked_count: number; macros?: Record<string, string> }>(`nodes/${nodeId}/questions/${ids ? `?ids=${ids}` : ''}`),
  today: () => api<Today>('me/today/'),
  reviews: () => api<{ due: ReviewItem[]; today: ReviewItem[]; daily_cap: number }>('me/reviews/'),
  bookSamples: (slug: string) => api<{ book: string; questions: Question[] }>(`books/${encodeURIComponent(slug)}/samples/`),
  startReview: (kind: 'chapter' | 'book', id: number) => api<ReviewSessionData>('me/reviews/start/', { body: { kind, id } }),
  reviewSession: (id: number) => api<ReviewSessionData>(`me/reviews/${id}/`),
  reviewMore: (id: number) => api<ReviewSessionData>(`me/reviews/${id}/more/`, { body: {} }),
  finishReview: (id: number) => api<ReviewSessionData>(`me/reviews/${id}/finish/`, { body: {} }),
  /** «این فصل را تمام کردم». */
  finishChapter: (chapterId: number) => api<{ due_on: string; days: number }>(`nodes/${chapterId}/finish/`, { body: {} }),
  search: (q: string, book = '') =>
    api<{ query: string; results: SearchResult[]; more?: boolean; too_short?: boolean }>(`search/?q=${encodeURIComponent(q)}${book ? `&book=${encodeURIComponent(book)}` : ''}`),
  quick: () => api<{ cards: (Flashcard & { box: number; hints: GradeHints })[]; questions: Question[] }>('me/quick/'),
  mistakes: (book = '') => api<Mistakes>(`me/mistakes/${book ? `?book=${encodeURIComponent(book)}` : ''}`),
  mistakeQuestions: (book = '') => api<{ questions: Question[]; locked_count: number }>(`me/mistakes/questions/${book ? `?book=${encodeURIComponent(book)}` : ''}`),
  mistakeReason: (questionId: number, reason: string) => api<{ reason: string; cards: number }>(`me/mistakes/${questionId}/reason/`, { body: { reason } }),
  answer: (questionId: number, choiceId: number) => api<AnswerResult>(`questions/${questionId}/answer/`, { body: { choice_id: choiceId } }),
  flashcards: (nodeId: number, doneOnly = false, ids?: string) =>
    api<{ flashcards: Flashcard[]; locked_count: number; book_id?: number; macros?: Record<string, string> }>(
      `nodes/${nodeId}/flashcards/${ids ? `?ids=${ids}` : doneOnly ? '?done=1' : ''}`,
    ),
  banners: () => api<Banner[]>('banners/'),
  bannerClick: (id: number) => api<{ ok: boolean }>(`banners/${id}/click/`, { method: 'POST' }),
  health: (baseUrl?: string) => api<{ status: string }>('health/', { baseUrl }),

  // Account
  requestOtp: (phone: string, appHash?: string) => api<{ sent: boolean; expires_in: number }>('auth/request-otp/', { body: { phone, app_hash: appHash }, timeoutMs: 25_000 }),
  verifyOtp: (body: { phone: string; code: string; device_name: string; platform: string; replace_session_id?: number }) =>
    api<VerifyResult>('auth/verify-otp/', { body }),
  /** «باز کردن وب اپ با حساب من» in the panel: a one-time code instead of an SMS (staff only). */
  panelLogin: (body: { code: string; device_name: string; platform: string; replace_session_id?: number }) =>
    api<VerifyResult>('auth/panel-login/', { body }),
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
  /** Copy a piece of a lesson: counted (30 a day) and given back with an invisible fingerprint. */
  copyText: (id: number, text: string, mode: string) =>
    api<{ text: string; used: number; limit: number; left: number }>(`nodes/${id}/copy/`, { body: { text, mode } }),
  editNote: (id: number, body: { body?: string; color?: string }) => api<Note>(`notes/${id}/`, { method: 'PATCH', body }),
  deleteNote: (id: number) => api<{ deleted: boolean }>(`notes/${id}/`, { method: 'DELETE' }),
  practiceState: (id: number) => api<PracticeState>(`nodes/${id}/practice/`),
  practiceReset: (id: number) => api<{ reset: number }>(`nodes/${id}/practice/reset/`, { method: 'POST' }),
  flashcardState: (id: number) => api<FlashcardState>(`nodes/${id}/flashcards/me/`),
  reviewFlashcard: (id: number, grade: Grade) => api<{ box: number; mastered: boolean }>(`flashcards/${id}/review/`, { body: { grade } }),
  dueFlashcards: () => api<{ count: number; flashcards: DueFlashcard[] }>('me/flashcards/due/'),
  reportQuestion: (id: number, reason: ReportReason, note: string) => api<{ reported: boolean }>(`questions/${id}/report/`, { body: { reason, note } }),
  reportFlashcard: (id: number, reason: ReportReason, note: string) => api<{ reported: boolean }>(`flashcards/${id}/report/`, { body: { reason, note } }),
  reportNode: (id: number, reason: ReportReason, note: string, place: ReportPlace = {}) =>
    api<{ reported: boolean }>(`nodes/${id}/report/`, { body: { reason, note, ...place } }),
  /** «اصلاح شد، ممنون»: reports fixed since last asked (each told once). */
  reportsFixed: () => api<{ fixed: { id: number; about: string }[] }>('me/reports/fixed/', { method: 'POST' }),
  startExam: (
    nodeId: number,
    body: { count: number; negative_marking: boolean; minutes?: number; focus_mistakes?: boolean; konkur_only?: boolean; years?: number[]; source?: number; only_studied?: boolean },
  ) => api<ExamDetail>(`nodes/${nodeId}/exams/`, { body }),
  exam: (id: number) => api<ExamDetail>(`exams/${id}/`),
  examInfo: (nodeId: number, source?: number) =>
    api<{
      questions: number;
      title: string;
      konkur?: number;
      years?: { year: number; count: number }[];
      /** A past konkur: how many of its tests are from chapters not studied yet. */
      source?: { count: number; unread: number; unread_chapters: string[] };
    }>(`nodes/${nodeId}/exam-info/${source ? `?source=${source}` : ''}`),
  pastExams: (slug: string) => api<PastExams>(`books/${slug}/past/`),
  pastQuestions: (slug: string, source: number) =>
    api<{ questions: Question[]; locked_count: number; title: string; macros?: Record<string, string> }>(`books/${slug}/past/questions/?source=${source}`),
  pastRepeats: (slug: string, names: string[]) =>
    api<{ questions: Question[]; locked_count: number; title: string; groups: number; macros?: Record<string, string> }>(
      `books/${slug}/past/repeats/?names=${encodeURIComponent(names.join('|'))}`,
    ),
  submitExam: (id: number, answers: Record<string, number | null>, doubts: number[] = []) =>
    api<ExamDetail>(`exams/${id}/submit/`, { body: { answers, doubts } }),
  myExams: () => api<ExamSummary[]>('me/exams/'),
  examPage: (page: number, book = '') => api<ExamPage>(`me/exams/?page=${page}${book ? `&book=${encodeURIComponent(book)}` : ''}`),
  library: () => api<Library>('me/library/'),
  updateLibraryBook: (bookId: number, body: { status?: LibraryShelfStatus; hidden?: boolean }) =>
    api<{ book_id: number; status: LibraryShelfStatus; hidden: boolean; position: number }>(`me/library/books/${bookId}/`, { method: 'PATCH', body }),
  reorderLibrary: (status: LibraryShelfStatus, book_ids: number[]) =>
    api<{ status: LibraryShelfStatus; book_ids: number[] }>('me/library/reorder/', { method: 'PATCH', body: { status, book_ids } }),
  appPages: () => api<AppPages>('app/pages/'),
  sitePage: (slug: string) => api<SitePageDetail>(`app/pages/${slug}/`),
  helpPage: (id: number) => api<{ id: number; title: string; body: string; updated_at: string }>(`app/help/${id}/`),
  formulaCommands: () => api<{ macros: Record<string, string> }>('formula-commands/'),
  bookChanges: (slug: string) => api<BookChanges>(`books/${slug}/changes/`),
  appVersion: (platform: string, build: number) => api<AppVersion>(`app/version/?platform=${platform}&build=${build}`),
  stats: () => api<Stats>('me/stats/'),
  offline: (slug: string) => api<OfflineBundle>(`books/${encodeURIComponent(slug)}/offline/`, { timeoutMs: 90_000 }),

  // Sales (prices always come from the server)
  offers: (book: string) => api<Offers>(`offers/?book=${encodeURIComponent(book)}`),
  createOrder: (body: { book?: string; plan?: number; major?: string }) => api<{ order_id: number; amount: number; pay_url: string }>('orders/', { body, timeoutMs: 30_000 }),
  order: (id: number, check = false) => api<OrderStatus>(`orders/${id}/${check ? '?check=1' : ''}`, { timeoutMs: 30_000 }),
  purchases: () => api<Purchases>('me/purchases/'),
};
