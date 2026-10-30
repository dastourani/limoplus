import { api } from './client';

export type Major = { slug: string; name: string; color: string; is_coming_soon: boolean };
export type BookListItem = { slug: string; title: string; price: number | null; chapter_count: number; has_free_part: boolean };
export type NodeSummary = {
  id: number;
  slug: string;
  kind: 'book' | 'chapter' | 'section';
  title: string;
  is_locked: boolean;
  has_summary?: boolean;
  question_count?: number;
  flashcard_count?: number;
};
export type ChapterSummary = NodeSummary & { sections: NodeSummary[] };
export type BookDetail = { slug: string; title: string; price: number | null; majors: string[]; chapters: ChapterSummary[] };
export type NodeDetail = {
  id: number;
  kind: NodeSummary['kind'];
  title: string;
  breadcrumb: { id: number; kind: NodeSummary['kind']; slug: string; title: string }[];
  summary: string;
  full: string;
  previous_id: number | null;
  next_id: number | null;
};
export type Question = {
  id: number;
  stem: string;
  choices: { id: number; text: string }[];
  difficulty: 'easy' | 'medium' | 'hard';
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

export const endpoints = {
  majors: () => api<Major[]>('majors/'),
  books: (major: string) => api<BookListItem[]>(`majors/${encodeURIComponent(major)}/books/`),
  book: (slug: string) => api<BookDetail>(`books/${encodeURIComponent(slug)}/`),
  node: (id: number) => api<NodeDetail>(`nodes/${id}/`),
  questions: (nodeId: number) => api<{ questions: Question[]; locked_count: number }>(`nodes/${nodeId}/questions/`),
  answer: (questionId: number, choiceId: number) => api<AnswerResult>(`questions/${questionId}/answer/`, { body: { choice_id: choiceId } }),
  flashcards: (nodeId: number) => api<{ flashcards: Flashcard[]; locked_count: number }>(`nodes/${nodeId}/flashcards/`),
  banners: (major: string) => api<Banner[]>(`banners/?major=${encodeURIComponent(major)}`),
  bannerClick: (id: number) => api<{ ok: boolean }>(`banners/${id}/click/`, { method: 'POST' }),
  health: (baseUrl?: string) => api<{ status: string }>('health/', { baseUrl }),
};
