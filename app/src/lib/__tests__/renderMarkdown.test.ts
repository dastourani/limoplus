import { describe, expect, it } from 'vitest';

import { setLabels } from '../labels';
import { setMacros } from '../macros';
import { setNumbering } from '../numbering';
import { renderMarkdown } from '../renderMarkdown';

describe('renderMarkdown offline SVG/image data URI + numbering + macros', () => {
  it('renders base64 SVG & PNG data URIs while blocking unsafe data:text/html and javascript: links', () => {
    setLabels([{ name: 'مثال', style: 'formal', numbered: true, icon: 'bookmark' }]);
    setMacros({ '\\R': '\\mathbb{R}' });
    setNumbering({
      chapter: 2,
      start: { مثال: 1 },
      refs: { 'ex-lim': { text: 'مثال ۲-۲', node: 42 } },
    });

    const md = [
      '![نمودار](data:image/svg+xml;base64,PHN2Zy8+)',
      '![عکس](data:image/png;base64,iVBORw0KGgo=)',
      '[بد](javascript:alert(1))',
      '![بد](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)',
      '::: مثال {#ex-lim}',
      'برای $x \\in \\R$',
      ':::',
      'رجوع به [[#ex-lim]]',
    ].join('\n\n');

    const html = renderMarkdown(md);
    expect(html).toContain('<img src="data:image/svg+xml;base64,PHN2Zy8+" alt="نمودار">');
    expect(html).toContain('<img src="data:image/png;base64,iVBORw0KGgo=" alt="عکس">');
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<img src="data:text/html');
    expect(html).toContain('مثال ۲-۲');
    expect(html).toContain('data-ref="ex-lim"');
    expect(html).toContain('ℝ');
  });
});
