"""Reproduksi IndexError pada JALUR AGENT LOOP NYATA.

Memanggil urutan persis seperti di agent_loop.py:
    1. _convert_alt_tool_call_syntax(assistant_text)  -- agent_loop.py:368
    2. _render_markdown_once(visible_text)            -- agent_loop.py:504 (no_stream)
    3. extract_tool_call(assistant_text)              -- agent_loop.py:506
dengan markdown 5 halaman + LaTeX bervariasi (tanpa tool_call, jadi
extract_tool_call harusnya return (None, None)).
"""
import os, sys, time
sys.path.insert(0, os.getcwd())

from garwa.cli.tool_schema import _convert_alt_tool_call_syntax
from garwa.cli.markdown_render import _render_markdown_once
from garwa.cli.json_repair import extract_tool_call

# --- bangun markdown 5 halaman + LaTeX bervariasi (sama dengan tes sebelumnya) ---
P = []
for p in range(5):
    P.append(f'# Halaman {p+1}: Matematika Lanjut\n\n')
    P.append('## Kalkulus\n\n')
    P.append(r'$$\frac{d}{dx}\left(\frac{x^2+1}{x-1}\right) = \frac{(x-1)(2x)-(x^2+1)}{(x-1)^2}$$')
    P.append('\n\n')
    P.append(r'$$\frac{d}{dx} \sin(x^2) = 2x\cos(x^2)$$')
    P.append('\n\n')
    P.append(r'$$\int x e^x\,dx = x e^x - e^x + C$$')
    P.append('\n\n')
    P.append(r'$$\int_0^1 x^2\,dx = \left[\frac{x^3}{3}\right]_0^1 = \frac{1}{3}$$')
    P.append('\n\n')
    P.append('### Matriks\n\n')
    P.append(r'$$\begin{bmatrix} a_{11} & a_{12} & a13 \\ a21 & a22 & a23 \\ a31 & a32 & a33 \end{bmatrix}$$')
    P.append('\n\n')
    P.append(r'$$\det(A) = a_{11}(a_{22}a_{33}-a_{23}a_{32}) - a_{12}(a_{21}a_{33}-a_{23}a_{31}) + a_{13}(a_{21}a_{32}-a_{22}a_{31})$$')
    P.append('\n\n')
    P.append('### Deret dan Limit\n\n')
    P.append(r'$$\sum_{n=0}^{\infty} a r^n = \frac{a}{1-r}, \quad |r|<1$$')
    P.append('\n\n')
    P.append(r'$$\lim_{x \to 0} \frac{\sin x}{x} = 1$$')
    P.append('\n\n')
    P.append(r'$$e = \lim_{n \to \infty} \left(1 + \frac{1}{n}\right)^n$$')
    P.append('\n\n')
    P.append('## Persamaan Diferensial\n\n')
    P.append(r'$$\frac{dy}{dx} + P(x)y = Q(x)$$')
    P.append('\n\n')
    P.append(r'$$y = e^{-\int P\,dx}\left(\int Q e^{\int P\,dx}\,dx + C\right)$$')
    P.append('\n\n')
    P.append('## Statistika dan Probabilitas\n\n')
    P.append(r'$$f(x) = \frac{1}{\sigma\sqrt{2\pi}} e^{-\frac{(x-\mu)^2}{2\sigma^2}}$$')
    P.append('\n\n')
    P.append(r'$$\sigma^2 = \frac{1}{N}\sum_{i=1}^{N}(x_i - \mu)^2$$')
    P.append('\n\n')
    P.append(r'$$P(A|B) = \frac{P(A \cap B)}{P(B)}$$')
    P.append('\n\n')
    P.append('## Aljabar Linear\n\n')
    P.append(r'$$\vec{u} \cdot \vec{v} = \sum_{i=1}^{n} u_i v_i$$')
    P.append('\n\n')
    P.append(r'$$\|\vec{v}\| = \sqrt{v_1^2 + v_2^2 + \cdots + v_n^2}$$')
    P.append('\n\n')
    P.append('## Kombinatorik\n\n')
    P.append(r'$$\binom{n}{k} = \frac{n!}{k!(n-k)!}$$')
    P.append('\n\n')
    P.append(r'$$(a+b)^n = \sum_{k=0}^{n} \binom{n}{k} a^{n-k}b^k$$')
    P.append('\n\n')
    P.append('## Tabel dengan LaTeX\n\n')
    P.append('| Simbol | Makna | Rumus |\n|---|---|---|\n')
    for i in range(30):
        P.append(f'| \\alpha_{i} | koefisien {i} | \\alpha_{i} = \\frac{{{i}}}{{{i}+1}} |\n')
    P.append('\n')
    P.append('## Kode dengan LaTeX komentar\n\n')
    P.append('```python\n')
    P.append('import math\n')
    P.append('# integral numerik dari 0 ke 1 dari x^2\n')
    P.append('def integral_x2(n=1000):\n')
    P.append('    h = 1.0 / n\n')
    P.append('    return h * sum((i*h)**2 for i in range(n))\n')
    P.append('```\n\n')
    P.append('---\n\n')

text = ''.join(P)
print('LEN:', len(text))

# --- jalur agent loop nyata ---
t = time.time()
try:
    converted = _convert_alt_tool_call_syntax(text)
    visible = converted.strip()
    if visible:
        _render_markdown_once(visible)
    name, args = extract_tool_call(converted)
    print('AGENTLOOP PIPELINE: %.3fs' % (time.time() - t))
    print('extract_tool_call ->', repr(name), repr(args)[:60])
    assert name is None, 'seharusnya tidak ada tool_call'
    print('SELESAI TANPA ERROR')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR TERJADI:', type(e).__name__, e)
    sys.exit(1)
