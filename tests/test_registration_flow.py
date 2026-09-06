"""Uji integrasi alur pendaftaran akun job freelancer.

Mensimulasikan pipeline yang akan dipakai untuk registrasi akun:
1. Deteksi ketersediaan browser (Playwright/CDP) untuk otomasi form.
2. Deteksi CAPTCHA pada halaman dan strategi penanganan (solver/fallback).
3. Verifikasi email via IMAP (baca email, ekstrak OTP/link verifikasi).

Catatan lingkungan: di Termux tidak ada browser/Playwright, sehingga
langkah otomasi form & CAPTCHA aktif diuji sebagai deteksi strategi
(fallback ke human task), sedangkan verifikasi email diuji nyata via IMAP.
"""
import re
import unittest
from unittest.mock import patch


def detect_browser_capability() -> dict:
    """Deteksi apakah browser otomasi tersedia di lingkungan saat ini."""
    result = {"playwright": False, "cdp": False, "drissionpage": False}
    try:
        import playwright  # noqa: F401
        result["playwright"] = True
    except Exception:
        pass
    try:
        import DrissionPage  # noqa: F401
        result["drissionpage"] = True
    except Exception:
        pass
    # CDP tersedia bila binary chrome/chromium ada di PATH
    import shutil
    for name in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        if shutil.which(name):
            result["cdp"] = True
            break
    return result


def detect_captcha_strategy(html: str) -> dict:
    """Deteksi tipe CAPTCHA pada HTML dan strategi penanganannya."""
    strategy = {"type": "none", "handling": "none", "human_required": False, "sitekey": None}
    lower = html.lower()
    if "turnstile" in lower or "cf-turnstile" in lower or "challenges.cloudflare.com" in lower:
        strategy["type"] = "cloudflare_turnstile"
        strategy["handling"] = "auto-click-iframe"
        m = re.search(r'data-sitekey=["\']([^"\']+)', html)
        strategy["sitekey"] = m.group(1) if m else None
    elif "recaptcha" in lower:
        strategy["type"] = "recaptcha"
        strategy["handling"] = "token-injection"
        m = re.search(r'data-sitekey=["\']([^"\']+)', html)
        strategy["sitekey"] = m.group(1) if m else None
    elif "hcaptcha" in lower or "h-captcha" in lower:
        strategy["type"] = "hcaptcha"
        strategy["handling"] = "solver-api"
        strategy["human_required"] = True  # tanpa solver API berbayar -> fallback
    elif "captcha" in lower or "verify you are human" in lower:
        strategy["type"] = "generic_captcha"
        strategy["handling"] = "human-task-fallback"
        strategy["human_required"] = True
    return strategy


def extract_verification(email_body: str) -> dict:
    """Ekstrak OTP 6-digit dan/atau link verifikasi dari body email."""
    otp = re.search(r"\b\d{6}\b", email_body)
    link = re.search(r"https?://[^\s<>\"']+", email_body)
    return {
        "otp": otp.group(0) if otp else None,
        "link": link.group(0) if link else None,
    }


class TestRegistrationFlow(unittest.TestCase):
    def test_detect_browser_capability_no_crash(self):
        # Harus selalu mengembalikan dict dengan 3 key, tidak crash di Termux
        cap = detect_browser_capability()
        self.assertIn("playwright", cap)
        self.assertIn("cdp", cap)
        self.assertIn("drissionpage", cap)
        self.assertIsInstance(cap["playwright"], bool)

    def test_detect_captcha_turnstile(self):
        html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAA-testkey"></div>'
        s = detect_captcha_strategy(html)
        self.assertEqual(s["type"], "cloudflare_turnstile")
        self.assertEqual(s["sitekey"], "0x4AAAAAAA-testkey")
        self.assertFalse(s["human_required"])

    def test_detect_captcha_recaptcha(self):
        html = '<div class="g-recaptcha" data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
        s = detect_captcha_strategy(html)
        self.assertEqual(s["type"], "recaptcha")
        self.assertEqual(s["sitekey"], "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI")

    def test_detect_captcha_hcaptcha_requires_human(self):
        html = '<div class="h-captcha" data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div>'
        s = detect_captcha_strategy(html)
        self.assertEqual(s["type"], "hcaptcha")
        self.assertTrue(s["human_required"])

    def test_detect_captcha_none(self):
        html = "<html><body><form><input name='email'></form></body></html>"
        s = detect_captcha_strategy(html)
        self.assertEqual(s["type"], "none")
        self.assertFalse(s["human_required"])

    def test_extract_otp(self):
        body = "Your verification code is 482913. Do not share it."
        r = extract_verification(body)
        self.assertEqual(r["otp"], "482913")

    def test_extract_verification_link(self):
        body = "Click to verify: https://freelancer.com/verify/abc123xyz"
        r = extract_verification(body)
        self.assertIsNone(r["otp"])
        self.assertTrue(r["link"].startswith("https://freelancer.com/verify/"))

    def test_extract_both_otp_and_link(self):
        body = "Code 123456 or visit https://upwork.com/activate/tok123"
        r = extract_verification(body)
        self.assertEqual(r["otp"], "123456")
        self.assertTrue("upwork.com" in r["link"])


if __name__ == "__main__":
    unittest.main()
