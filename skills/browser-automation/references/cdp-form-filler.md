# CDP & Form Filler Technical Guide

Dokumen ini berisi contoh script Python reusable untuk automasi browser, pengisian form profil/registrasi, dan penanganan session state.

## 1. Helper Script Form Autofill (Playwright)

```python
import time
import random
from playwright.sync_api import Page

def fill_form_field(page: Page, selector: str, value: str):
    \"\"\"Mengisi field input dengan pengetikan ritme manusia.\"\"\"
    element = page.wait_for_selector(selector, state=\"visible\", timeout=10000)
    element.click()
    time.sleep(random.uniform(0.1, 0.3))

    # Clear existing content
    element.fill(\"\")

    # Type character by character
    for char in value:
        element.type(char, delay=random.randint(30, 90))

    # Dispatch blur event
    page.evaluate(\"(sel) => document.querySelector(sel).dispatchEvent(new Event('blur'))\", selector)

def auto_fill_registration(page: Page, user_profile: dict):
    \"\"\"Mengisi form registrasi berbasis pola selector standar.\"\"\"
    mappings = [
        ([\"input[name='email']\", \"input[type='email']\", \"#email\"], user_profile[\"email\"]),
        ([\"input[name='username']\", \"#username\", \"input[name='user']\"], user_profile[\"username\"]),
        ([\"input[name='password']\", \"input[type='password']\", \"#password\"], user_profile[\"password\"]),
        ([\"input[name='full_name']\", \"input[name='name']\", \"#name\"], user_profile[\"full_name\"]),
        ([\"input[name='bio']\", \"textarea[name='bio']\", \"#bio\"], user_profile.get(\"bio\", \"\")),
    ]

    for selectors, val in mappings:
        if not val:
            continue
        for sel in selectors:
            try:
                if page.is_visible(sel):
                    fill_form_field(page, sel, val)
                    break
            except Exception:
                continue
```

## 2. Remote CDP Browser Connector

```python
from playwright.sync_api import sync_playwright

def connect_to_cdp(cdp_url: str = \"http://localhost:9222\"):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        default_context = browser.contexts[0]
        page = default_context.pages[0] if default_context.pages else default_context.new_page()
        return browser, page
```

## 3. Session & Cookie Preservation

```python
def save_session(page, storage_path: str):
    \"\"\"Menyimpan localStorage dan cookies ke file JSON untuk sesi berikutnya.\"\"\"
    storage = page.context.storage_state()
    with open(storage_path, \"w\") as f:
        f.write(str(storage))

def load_session(page, storage_path: str):
    \"\"\"Memuat state tersimpan untuk melanjutkan sesi yang sama.\"\"\"
    with open(storage_path, \"r\") as f:
        page.context.clear_storage_state()
        page.context.load_storage_state(f.read())
```

## 4. Anti-Bot Stealth Notes

- Gunakan `stealth` plugin (mis. `playwright-stealth`) atau DrissionPage untuk meniru browser sungguhan.
- Hindari User-Agent Headless Chrome generik (`HeadlessChrome/...`).
- Profil browser sungguhan via CDP (`--remote-debugging-port=9222`) dengan cookies aktif lebih sulit terdeteksi.
- Tambahkan delay random antar interaksi untuk meniru perilaku manusia.
