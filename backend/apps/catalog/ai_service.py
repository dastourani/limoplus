"""Unified LLM service for cleaning raw LaTeX chunks into standard LimooKhan Markdown.

Supports Google Gemini (via official REST API) and any OpenAI-compatible provider
(Groq, OpenAI, DeepSeek, AvalAI, etc.).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.catalog.models import AIProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """شما یک متخصص حرفه‌ای تبدیل اسناد علمی و دانشگاهی LaTeX به مارک‌داون استاندارد پلتفرم «لیموخوان» هستید.
وظیفه شما تبدیل دقیق، تمیز و ساختاریافته متن ورودی به مارک‌داون استاندارد است.

قوانین سخت‌گیرانه و غیرقابل تغییر:
۱. فرمول‌های ریاضی و نمادهای علمی:
   - تمام فرمول‌ها و متغیرهای ریاضی را کاملاً دست‌نخورده و بدون کوچک‌ترین تغییر در اندیس‌ها، علائم یا ساختار نگه دارید.
   - فرمول‌های درون‌خطی به شکل $...$ و فرمول‌های بلوکی به شکل $$...$$ باشند.
۲. کادرها و محیط‌های آموزشی:
   - محیط‌های تعریف، قضیه، مثال، نکته، تذکر، تمرین و نتیجه را به صورت ساختار سه دونقطه ::: بنویسید؛ مانند:
     :::تعریف
     متن تعریف
     :::
     :::قضیه
     متن قضیه
     :::
     :::نکته
     متن نکته
     :::
     :::مثال
     متن مثال
     :::
۳. پاک‌سازی کدهای زاید چیدمان لاتک:
   - دستورات تنظیم ابعاد و چیدمان مثل 0.6cm=، width=...، \\vspace، \\hspace، \\noindent، \\centering، minipage، multicols را حذف کرده و فقط متن علمی داخل آن‌ها را تمیز استخراج کنید.
۴. نمودارها و تصاویر:
   - کدهای ترسیمی پیچیده مانند TikZ یا pspicture را که تبدیل مستقیم ندارند به شکل «> [نمودار TikZ]» قرار دهید.
   - تصاویر معمولی به شکل ![توضیح](نام_فایل.png) باشد.
۵. خروجی فقط و فقط متن تبدیل‌شده مارک‌داون باشد، بدون هیچ سلام، تعارف یا توضیحات اضافی.
"""


def clean_chunk_with_ai(provider: AIProvider, raw_text: str, timeout: int = 40) -> tuple[bool, str]:
    """Call the configured AI provider to clean a raw LaTeX/text chunk.

    Returns:
        (success: bool, result_text_or_error_message: str)
    """
    if not provider.api_key:
        return False, "کلید API برای این ارائه‌دهنده تنظیم نشده است."

    if provider.provider_type == provider.ProviderType.GEMINI:
        return _call_gemini(provider, raw_text, timeout=timeout)
    else:
        return _call_openai_compatible(provider, raw_text, timeout=timeout)


def _call_gemini(provider: AIProvider, raw_text: str, timeout: int) -> tuple[bool, str]:
    model = (provider.model_name or "gemini-2.0-flash").strip()
    api_key = provider.api_key.strip()
    
    # If base_url is specified (for proxy / reverse-proxy), use it; otherwise official Google API
    if provider.base_url and provider.base_url.strip():
        base = provider.base_url.strip().rstrip("/")
        url = f"{base}/v1beta/models/{model}:generateContent"
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{SYSTEM_PROMPT}\n\nمتن ورودی LaTeX برای تبدیل:\n\n{raw_text}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": "LimooKhan/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if not candidates:
                return False, "پاسخی از مدل هوش مصنوعی دریافت نشد."
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                return False, "محتوای پاسخ خالی است."
            text = parts[0].get("text", "").strip()
            # Strip triple backtick markdown wrappers if LLM wrapped everything
            if text.startswith("```markdown"):
                text = text[len("```markdown"):].strip()
            elif text.startswith("```md"):
                text = text[len("```md"):].strip()
            elif text.startswith("```"):
                text = text[3:].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
            return True, text
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        logger.warning("Gemini API HTTP error %d: %s", e.code, err_msg)
        return False, f"خطای اتصال به هوش مصنوعی گوگل ({e.code}): {err_msg[:200]}"
    except Exception as e:
        logger.exception("Error calling Gemini API")
        return False, f"خطا در برقراری ارتباط با مدل هوش مصنوعی: {str(e)}"


def _call_openai_compatible(provider: AIProvider, raw_text: str, timeout: int) -> tuple[bool, str]:
    base_url = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": provider.model_name or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"متن ورودی LaTeX برای تبدیل:\n\n{raw_text}"},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key.strip()}",
            "User-Agent": "LimooKhan/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                return False, "پاسخی از مدل هوش مصنوعی دریافت نشد."
            msg = choices[0].get("message", {})
            text = msg.get("content", "").strip()
            # Strip triple backtick markdown wrappers if LLM wrapped everything
            if text.startswith("```markdown"):
                text = text[len("```markdown"):].strip()
            elif text.startswith("```md"):
                text = text[len("```md"):].strip()
            elif text.startswith("```"):
                text = text[3:].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
            return True, text
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        logger.warning("OpenAI-compatible API HTTP error %d: %s", e.code, err_msg)
        return False, f"خطای اتصال به ارائه‌دهنده هوش مصنوعی ({e.code}): {err_msg[:200]}"
    except Exception as e:
        logger.exception("Error calling OpenAI-compatible API")
        return False, f"خطا در برقراری ارتباط با مدل هوش مصنوعی: {str(e)}"
