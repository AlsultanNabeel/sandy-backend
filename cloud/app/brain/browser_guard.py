"""What stops the browser on a page whatever it was asked: a password field, a card field, a
captcha, or a payment page (`forbidden`).

It reads a snapshot of the page (`{url, fields, frames, marks}`): the live browser's comes from
`SNAPSHOT_JS`, run before every step of a fill; a page read by a plain request gives the same
from its HTML (`of_html`). A password field is also how a page that wants a sign-in is known
(`tools_browser`): Sandy never types one, he signs in by hand on his phone.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from app.brain import lang

PASSWORD, CARD, CAPTCHA, PAYMENT = "password", "card", "captcha", "payment"

# Run in the page: its fields, frames and the containers captchas draw in, as JSON.
SNAPSHOT_JS = """(() => {
  const label = (el) => {
    if (el.labels && el.labels.length) return el.labels[0].innerText || "";
    return el.getAttribute("aria-label") || "";
  };
  const fields = [...document.querySelectorAll("input, select, textarea")].map((el) => ({
    type: (el.getAttribute("type") || el.tagName).toLowerCase(), name: el.name || "", id: el.id || "",
    autocomplete: el.getAttribute("autocomplete") || "", placeholder: el.getAttribute("placeholder") || "",
    label: label(el).slice(0, 120)}));
  const frames = [...document.querySelectorAll("iframe")].map((f) => f.src || "");
  const marks = [...document.querySelectorAll(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]")]
    .map((el) => el.className || "data-sitekey");
  return JSON.stringify({url: location.href, fields, frames, marks});
})()"""

_CARD = re.compile(r"card.?(number|num|no)|cc.?(num|number)|\bcvv\b|\bcvc\b|\bcsc\b|security.?code|expir"
                   r"|رقم\s*البطاق|البطاقة\s*الائتمان|بطاقة\s*ائتمان|تاريخ\s*الانتهاء", re.I)
_CAPTCHA_FRAMES = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare\.com|turnstile|arkoselabs|funcaptcha"
                             r"|geetest", re.I)
_CAPTCHA_MARKS = re.compile(r"g-recaptcha|h-captcha|cf-turnstile|data-sitekey", re.I)
_PAYMENT_PATH = re.compile(r"/(checkout|payment|payments|pay|billing)(/|$)", re.I)
_PAYMENT_HOSTS = ("paypal.com", "checkout.stripe.com", "pay.google.com")


def _payment(url: str) -> bool:
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    return (any(host == h or host.endswith("." + h) for h in _PAYMENT_HOSTS)
            or bool(_PAYMENT_PATH.search(parts.path or "/")))


def forbidden(snapshot: Dict[str, Any]) -> Optional[str]:
    """Why the browser stops on this page, or None."""
    fields = [f for f in snapshot.get("fields") or [] if isinstance(f, dict)]
    if any(str(f.get("type", "")).lower() == "password" for f in fields):
        return PASSWORD
    for f in fields:
        if str(f.get("autocomplete", "")).lower().startswith("cc-"):
            return CARD
        words = " ".join(str(f.get(k) or "") for k in ("name", "id", "placeholder", "label"))
        if _CARD.search(words):
            return CARD
    if any(_CAPTCHA_FRAMES.search(str(s or "")) for s in snapshot.get("frames") or []) or \
            any(_CAPTCHA_MARKS.search(str(m or "")) for m in snapshot.get("marks") or []):
        return CAPTCHA
    if _payment(snapshot.get("url", "")):
        return PAYMENT
    return None


def of_html(markup: Any, url: str) -> Dict[str, Any]:
    """The snapshot of a page read by a plain request."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(markup or "", "html.parser")
    labels = {str(lab.get("for")): lab.get_text(" ", strip=True) for lab in soup.find_all("label") if lab.get("for")}
    fields = [{"type": str(el.get("type") or el.name).lower(), "name": str(el.get("name") or ""),
               "id": str(el.get("id") or ""), "autocomplete": str(el.get("autocomplete") or ""),
               "placeholder": str(el.get("placeholder") or ""),
               "label": labels.get(str(el.get("id") or ""), str(el.get("aria-label") or ""))}
              for el in soup.find_all(["input", "select", "textarea"])]
    frames = [str(f.get("src") or "") for f in soup.find_all("iframe")]
    marks = [" ".join(el.get("class") or []) or "data-sitekey"
             for el in soup.select(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]")]
    return {"url": url, "fields": fields, "frames": frames, "marks": marks}


def told(why: str, site: str) -> str:
    """The stop, said to him in his language."""
    return lang.say(f"browser_forbidden_{why}", site=site)
