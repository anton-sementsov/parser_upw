import logging
from typing import Any, Dict, Optional
from datetime import datetime

import requests

from settings import config


logger = logging.getLogger(__name__)


def _get_telegram_params() -> Optional[Dict[str, Any]]:
    token = getattr(config, 'TELEGRAM_BOT_TOKEN', None)
    chat_id = getattr(config, 'TELEGRAM_CHAT_ID', None)
    thread_id = getattr(config, 'TELEGRAM_THREAD_ID', None)
    if not token or not chat_id:
        logger.debug('Telegram credentials not configured; skipping notifications')
        return None
    return {
        'token': token,
        'chat_id': chat_id,
        'thread_id': thread_id,
    }


def format_job_message(job: Dict[str, Any]) -> str:
    """
    Format a job dictionary into a Telegram-friendly message with `key: value` lines.
    """
    # Ensure string conversion and handle None values
    def _val(value: Any) -> str:
        if value is None:
            return ''
        return str(value)

    # job_tags can be JSON string or list; normalize to comma-separated
    tags_value = job.get('job_tags')
    if isinstance(tags_value, list):
        tags_text = ', '.join(tags_value)
    else:
        tags_text = _val(tags_value)
    # Truncate description to first 800 characters
    desc_full = _val(job.get('job_description'))
    description = (desc_full[:800] + '…') if len(desc_full) > 800 else desc_full

    # Short date formatting: YYYY-MM-DD HH:MM
    def _short_date(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M')
        s = _val(value)
        if not s:
            return ''
        try:
            s_norm = s.replace('Z', '')
            dt = datetime.fromisoformat(s_norm)
            return dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            return s[:16] if len(s) >= 16 else s

    separator = '---'
    message_lines = [
        f"{_val(job.get('job_title'))}",
        f"---",
        f"{_val(job.get('job_url'))}",
        f"---",

        f"{_short_date(job.get('posted_date'))}",
        f"---",
        f"{description}",
    ]
    body = '\n'.join(message_lines)

    return f"{separator}\n{body}\n{separator}"


def send_telegram_message(text: str) -> bool:
    params = _get_telegram_params()
    if params is None:
        return False

    token = params['token']
    chat_id = params['chat_id']
    thread_id = params['thread_id']

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {
        'chat_id': chat_id,
        'text': text,
        'disable_web_page_preview': True,
    }
    if thread_id:
        payload['message_thread_id'] = thread_id

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.ok:
            logger.info('Telegram message sent')
            return True
        logger.error(f'Telegram send failed: HTTP {resp.status_code} - {resp.text}')
        return False
    except Exception as exc:
        logger.exception(f'Error sending Telegram message: {exc}')
        return False


def notify_new_job(job: Dict[str, Any]) -> None:
    """
    Send a formatted Telegram notification for a new job.
    """
    text = format_job_message(job)
    send_telegram_message(text)


