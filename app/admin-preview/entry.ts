/**
 * The app's own lesson renderer, bundled for the panel's live preview (backend/apps/catalog/static/catalog/limo-preview.js),
 * so the panel shows exactly what learners see. Rebuild after changing renderMarkdown.ts or reviewCard.ts:
 *   npm run build:admin-preview
 */
import { CONTENT_CSS, renderMarkdown, renderSummary } from '../src/lib/renderMarkdown';
import { jumpTarget, parseParts } from '../src/lib/reviewCard';

(globalThis as unknown as { LimoPreview: unknown }).LimoPreview = { CONTENT_CSS, renderMarkdown, renderSummary, parseParts, jumpTarget };
