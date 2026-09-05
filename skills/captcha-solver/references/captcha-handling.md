# CAPTCHA Handling & Injection Guide

Panduan teknis penanganan CAPTCHA pada script Playwright dan browser automation.

## 1. Cloudflare Turnstile Auto-Clicker

```python
def pass_turnstile(page, timeout=10000):
    \"\"\"Mencari iframe Turnstile dan mengkliknya jika muncul.\"\"\"
    try:
        page.wait_for_selector('iframe[src*=challenges.cloudflare.com]', timeout=timeout)
        frames = page.frames
        for frame in frames:
            if 'challenges.cloudflare.com' in frame.url:
                checkbox = frame.wait_for_selector('input[type=checkbox], body', timeout=3000)
                if checkbox:
                    checkbox.click()
                    print('Turnstile checkbox clicked.')
                    return True
    except Exception as e:
        print(f'Turnstile not found or already passed: {e}')
    return False
```

## 2. reCAPTCHA Token Injection Example

```python
def inject_recaptcha_token(page, token: str):
    \"\"\"Menyuntikkan token hasil solver ke dalam DOM.\"\"\"
    js_script = f\"\"\"
        const el = document.getElementById('g-recaptcha-response') || document.querySelector('[name=g-recaptcha-response]');
        if (el) {{
            el.style.display = 'block';
            el.value = '{token}';
        }}
    \"\"\"
    page.evaluate(js_script)
    print('reCAPTCHA token injected successfully.')
```

## 3. hCaptcha Response Injection

```python
def inject_hcaptcha(page, token: str):
    \"\"\"Menginjeksi token hCaptcha ke hidden field.\"\"\"
    page.evaluate(f\"\"\"
        const el = document.getElementById('h-captcha-response');
        if (el) {{ el.value = '{token}'; }}
    \"\"\")
```

## 4. Notes Anti-Detection

- Selalu gunakan stealth mode dan delay random.
- Solver API eksternal (2Captcha/CapSolver) memerlukan API key dan biaya per token.
- Untuk CAPTCHA gambar yang sangat sulit, gunakan fallback ke operator manusia.
