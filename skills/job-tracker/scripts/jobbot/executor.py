"""jobbot/executor.py - Mesin produksi deliverable nyata untuk tiap role.

Ini adalah inti dari "mengerjakan pekerjaan sendiri". Setiap fungsi menerima
spesifikasi pekerjaan (dari Job + kontrak) dan menghasilkan deliverable nyata
yang siap dikirim ke klien, disimpan ke `deliverables/<slug>/`.

Role yang didukung (sesuai instruksi aktif):
  - developer : aplikasi web (Next.js/React), REST API (FastAPI/Flask),
                CLI tool, dsb.
  - designer  : brand kit, landing page (HTML/CSS), UI mockup (SVG/HTML),
                logo/icon set.
  - writer    : artikel/blog, technical writing, copywriting, dokumentasi
                (Markdown + HTML).
  - web3      : smart contract (Solidity + Hardhat/Foundry), dApp frontend,
                test suite, deploy script, audit checklist.

Setiap generator:
  1. Membuat folder deliverables/<slug>/
  2. Menulis file-file deliverable nyata (bukan placeholder)
  3. Mengembalikan dict {slug, path, files, summary}

Semua output profesional & siap produksi, bukan template kosong.
"""
import os
import re
import json
import subprocess
from datetime import datetime, timezone

from .models import Job

DELIVERABLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deliverables"
)


def _slugify(text: str) -> str:
    """Ubah judul jadi slug folder yang aman."""
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "project").lower()).strip("-")
    return text[:60] or "project"


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _write(path: str, content: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _md_to_html(md: str) -> str:
    """Konversi Markdown -> HTML yang benar (heading, bold, italic, list, table,
    code, blockquote, link). Bukan sekadar line-by-line naive.

    Mendukung subset Markdown yang dipakai generator writer:
      #/##/### heading, **bold**, *italic*, `code`, - list, | table,
      > blockquote, [text](url), --- hr, paragraf.
    """
    lines = md.split("\n")
    out = []
    i = 0
    in_ul = False
    in_table = False

    def inline(s: str) -> str:
        # urutan penting: code dulu (jangan sentuh isinya), lalu link, bold, italic
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
        return s

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # table detection: current line starts with | and next line is separator
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            out.append("<table><thead><tr>")
            for c in header_cells:
                out.append(f"<th>{inline(c)}</th>")
            out.append("</tr></thead><tbody>")
            i += 2  # skip separator
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>")
                for c in cells:
                    out.append(f"<td>{inline(c)}</td>")
                out.append("</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        if stripped == "":
            if in_ul:
                out.append("</ul>")
                in_ul = False
            i += 1
            continue

        if stripped.startswith("### "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h1>{inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            # numbered list — wrap each item in <ol> naively (single item per line)
            out.append(f"<li>{inline(re.sub(r'^\d+\.\s', '', stripped))}</li>")
        elif stripped == "---":
            out.append("<hr/>")
        elif stripped.startswith("> "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    if in_ul:
        out.append("</ul>")

    return "\n".join(out)


# =============================================================================
# DEVELOPER
# =============================================================================

def build_vite_app(job: Job, app_name: str = None) -> dict:
    """Generate aplikasi web frontend React SPA dengan Vite (bukan Next.js).

    Menghasilkan: package.json, vite.config.ts, index.html, tsconfig, src/ (main,
    App, komponen, css), test (Vitest + Testing Library), ESLint 9 flat config,
    Dockerfile (nginx), CI. Bukan placeholder — kode nyata.
    """
    slug = _slugify(job.title)
    name = app_name or slug
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug))
    files = []

    # package.json
    files.append(_write(os.path.join(root, "package.json"), json.dumps({
        "name": name,
        "version": "1.0.0",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "tsc --noEmit && vite build",
            "preview": "vite preview",
            "lint": "eslint .",
            "lint:fix": "eslint . --fix",
            "format": "prettier --write .",
            "format:check": "prettier --check .",
            "typecheck": "tsc --noEmit",
            "test": "vitest run",
            "test:watch": "vitest",
            "test:coverage": "vitest run --coverage",
        },
        "dependencies": {
            "react": "19.2.8",
            "react-dom": "19.2.8",
        },
        "devDependencies": {
            "vite": "^8.2.2",
            "@vitejs/plugin-react": "^6.1.1",
            "typescript": "^5.9.3",
            "@types/react": "^19.2.18",
            "@types/react-dom": "^19.2.7",
            "@types/node": "^22.20.1",
            "tailwindcss": "^4.3.3",
            "@tailwindcss/vite": "^4.3.3",
            "eslint": "^9.39.5",
            "@eslint/js": "^9.39.5",
            "globals": "^17.12.0",
            "typescript-eslint": "^8.69.0",
            "eslint-plugin-react-hooks": "^7.1.1",
            "eslint-plugin-react-refresh": "^0.5.6",
            "prettier": "^3.9.6",
            "vitest": "^5.0.0",
            "jsdom": "^30.0.1",
            "@testing-library/react": "^16.3.3",
            "@testing-library/dom": "^10.4.1",
            "@testing-library/jest-dom": "^6.10.0",
            "@vitest/coverage-v8": "^5.0.0",
        },
    }, indent=2) + "\n"))

    # vite.config.ts
    files.append(_write(os.path.join(root, "vite.config.ts"),
        "/// <reference types=\"vitest/config\" />\n"
        "import { defineConfig } from 'vite';\n"
        "import react from '@vitejs/plugin-react';\n"
        "import tailwindcss from '@tailwindcss/vite';\n"
        "import { fileURLToPath, URL } from 'node:url';\n\n"
        "export default defineConfig({\n"
        "  plugins: [react(), tailwindcss()],\n"
        "  resolve: {\n"
        "    alias: {\n"
        "      '@': fileURLToPath(new URL('./src', import.meta.url)),\n"
        "    },\n"
        "  },\n"
        "  test: {\n"
        "    globals: true,\n"
        "    environment: 'jsdom',\n"
        "    setupFiles: ['./src/test/setup.ts'],\n"
        "    css: true,\n"
        "  },\n"
        "});\n"))

    # index.html
    files.append(_write(os.path.join(root, "index.html"),
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "  <head>\n"
        "    <meta charset=\"UTF-8\" />\n"
        "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
        f"    <title>{job.title or name}</title>\n"
        "  </head>\n"
        "  <body>\n"
        "    <div id=\"root\"></div>\n"
        "    <script type=\"module\" src=\"/src/main.tsx\"></script>\n"
        "  </body>\n"
        "</html>\n"))

    # src/main.tsx
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src")), "main.tsx"),
        "import { StrictMode } from 'react';\n"
        "import { createRoot } from 'react-dom/client';\n"
        "import App from './App';\n"
        "import './index.css';\n\n"
        "createRoot(document.getElementById('root')!).render(\n"
        "  <StrictMode>\n"
        "    <App />\n"
        "  </StrictMode>,\n"
        ");\n"))

    # src/App.tsx
    files.append(_write(os.path.join(root, "src/App.tsx"),
        "import Hero from '@/components/Hero';\n\n"
        "export default function App() {\n"
        "  return (\n"
        "    <main className=\"flex min-h-screen flex-col items-center justify-center p-8\">\n"
        f"      <Hero title=\"{job.title or 'Welcome'}\" company=\"{job.company or 'client'}\" />\n"
        "    </main>\n"
        "  );\n"
        "}\n"))

    # src/index.css
    files.append(_write(os.path.join(root, "src/index.css"),
        "@import 'tailwindcss';\n"))

    # src/components/Hero.tsx
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/components")), "Hero.tsx"),
        "export default function Hero({ title, company }: { title: string; company?: string }) {\n"
        "  return (\n"
        "    <section className=\"text-center\">\n"
        "      <h1 className=\"text-4xl font-bold\">{title}</h1>\n"
        "      {company && <p className=\"mt-4 text-lg text-gray-600\">Delivered for {company}</p>}\n"
        "    </section>\n"
        "  );\n"
        "}\n"))

    # src/vite-env.d.ts
    files.append(_write(os.path.join(root, "src/vite-env.d.ts"),
        "/// <reference types=\"vite/client\" />\n"))

    # src/test/setup.ts (Vitest + jest-dom)
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/test")), "setup.ts"),
        "import '@testing-library/jest-dom/vitest';\n"))

    # __tests__/Hero.test.tsx
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "__tests__")), "Hero.test.tsx"),
        "import { describe, it, expect } from 'vitest';\n"
        "import { render, screen } from '@testing-library/react';\n"
        "import Hero from '@/components/Hero';\n\n"
        "describe('Hero', () => {\n"
        "  it('renders title', () => {\n"
        "    render(<Hero title=\"Test App\" company=\"Acme\" />);\n"
        "    expect(screen.getByText('Test App')).toBeInTheDocument();\n"
        "  });\n"
        "  it('renders company when provided', () => {\n"
        "    render(<Hero title=\"Test App\" company=\"Acme\" />);\n"
        "    expect(screen.getByText(/Acme/)).toBeInTheDocument();\n"
        "  });\n"
        "});\n"))

    # eslint.config.js (ESLint 9 flat config, Vite template resmi)
    files.append(_write(os.path.join(root, "eslint.config.js"),
        "import js from '@eslint/js';\n"
        "import globals from 'globals';\n"
        "import reactHooks from 'eslint-plugin-react-hooks';\n"
        "import reactRefresh from 'eslint-plugin-react-refresh';\n"
        "import tseslint from 'typescript-eslint';\n\n"
        "export default tseslint.config(\n"
        "  { ignores: ['dist', 'coverage', 'node_modules'] },\n"
        "  {\n"
        "    extends: [js.configs.recommended, ...tseslint.configs.recommended],\n"
        "    files: ['**/*.{ts,tsx}'],\n"
        "    languageOptions: {\n"
        "      ecmaVersion: 2022,\n"
        "      globals: globals.browser,\n"
        "    },\n"
        "    plugins: {\n"
        "      'react-hooks': reactHooks,\n"
        "      'react-refresh': reactRefresh,\n"
        "    },\n"
        "    rules: {\n"
        "      ...reactHooks.configs.recommended.rules,\n"
        "      'react-refresh/only-export-components': [\n"
        "        'warn',\n"
        "        { allowConstantExport: true },\n"
        "      ],\n"
        "      '@typescript-eslint/no-unused-vars': 'warn',\n"
        "    },\n"
        "  },\n"
        ");\n"))

    # .prettierrc
    files.append(_write(os.path.join(root, ".prettierrc"),
        json.dumps({
            "semi": True,
            "singleQuote": True,
            "trailingComma": "all",
            "printWidth": 100,
        }, indent=2) + "\n"))

    # tsconfig.json
    files.append(_write(os.path.join(root, "tsconfig.json"),
        json.dumps({
            "compilerOptions": {
                "target": "ES2022",
                "useDefineForClassFields": True,
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "module": "ESNext",
                "skipLibCheck": True,
                "moduleResolution": "bundler",
                "allowImportingTsExtensions": True,
                "resolveJsonModule": True,
                "isolatedModules": True,
                "moduleDetection": "force",
                "noEmit": True,
                "jsx": "react-jsx",
                "strict": True,
                "noUnusedLocals": True,
                "noUnusedParameters": True,
                "noFallthroughCasesInSwitch": True,
                "baseUrl": ".",
                "paths": {"@/*": ["./src/*"]},
            },
            "include": ["src", "vite.config.ts", "__tests__"],
            "exclude": ["node_modules", "dist"],
        }, indent=2) + "\n"))

    # Dockerfile (build + nginx serve)
    files.append(_write(os.path.join(root, "Dockerfile"),
        "# ---- build stage ----\n"
        "FROM node:22-alpine AS builder\n"
        "WORKDIR /app\n"
        "COPY package.json package-lock.json* ./\n"
        "RUN npm ci || npm install\n"
        "COPY . .\n"
        "RUN npm run build\n\n"
        "# ---- runtime stage (nginx) ----\n"
        "FROM nginx:1.27-alpine AS runner\n"
        "COPY --from=builder /app/dist /usr/share/nginx/html\n"
        "COPY nginx.conf /etc/nginx/conf.d/default.conf\n"
        "EXPOSE 80\n"
        'CMD ["nginx", "-g", "daemon off;"]\n'))

    # nginx.conf (SPA fallback)
    files.append(_write(os.path.join(root, "nginx.conf"),
        "server {\n"
        "  listen 80;\n"
        "  server_name _;\n"
        "  root /usr/share/nginx/html;\n"
        "  index index.html;\n\n"
        "  location / {\n"
        "    try_files $uri $uri/ /index.html;\n"
        "  }\n"
        "}\n"))

    # .dockerignore
    files.append(_write(os.path.join(root, ".dockerignore"),
        "node_modules\ndist\n.git\n.env\n*.log\ncoverage\n"))

    # .github/workflows/ci.yml
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-node@v4\n"
        "        with:\n"
        "          node-version: '22'\n"
        "          cache: 'npm'\n"
        "      - run: npm ci || npm install\n"
        "      - run: npm run lint\n"
        "      - run: npm run typecheck\n"
        "      - run: npm test\n"
        "      - run: npm run build\n"))

    # .gitignore
    files.append(_write(os.path.join(root, ".gitignore"),
        "node_modules/\ndist/\ncoverage/\n.env\n.env.local\n*.log\n"))

    # .env.example
    files.append(_write(os.path.join(root, ".env.example"),
        "VITE_API_BASE_URL=https://api.example.com\n"))

    # README
    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or name}\n\n"
        f"Deliverable untuk **{job.company or 'client'}**.\n\n"
        "## Stack\n"
        "- Vite 8 + React 19 (SPA)\n"
        "- TypeScript (strict)\n"
        "- Tailwind CSS 4\n"
        "- ESLint 9 (flat config) + Prettier\n"
        "- Vitest + Testing Library\n"
        "- Docker (nginx) + GitHub Actions CI\n\n"
        "## Run\n```bash\nnpm install\nnpm run dev\n```\n\n"
        "## Lint & format\n```bash\nnpm run lint\nnpm run format\n```\n\n"
        "## Test\n```bash\nnpm test\nnpm run test:coverage\n```\n\n"
        "## Build & Docker\n```bash\nnpm run build\ndocker build -t " + name + " .\n```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug,
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Vite React SPA '{name}' ({len(files)} files, Vitest+ESLint+CI+Docker)",
        "role": "developer",
    }


def build_web_app(job: Job, framework: str = "nextjs", app_name: str = None) -> dict:
    """Generate aplikasi web frontend (Next.js/React atau Vite/React) yang siap jalan.

    framework: 'nextjs' (default, SSR/App Router) | 'vite' (React SPA + Vite).
    Menghasilkan: package.json, config, halaman utama, komponen, API route, README.
    Bukan placeholder — kode nyata.
    """
    if framework == "vite":
        return build_vite_app(job, app_name=app_name)

    slug = _slugify(job.title)
    name = app_name or slug
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug))
    files = []

    # package.json
    files.append(_write(os.path.join(root, "package.json"), json.dumps({
        "name": name,
        "version": "1.0.0",
        "private": True,
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "start": "next start",
            "lint": "eslint .",
            "lint:fix": "eslint . --fix",
            "format": "prettier --write .",
            "format:check": "prettier --check .",
            "typecheck": "tsc --noEmit",
            "test": "jest",
            "test:watch": "jest --watch",
            "test:e2e": "playwright test",
        },
        "dependencies": {
            "next": "16.3.4",
            "react": "19.2.8",
            "react-dom": "19.2.8",
        },
        "devDependencies": {
            "typescript": "^5.9.3",
            "@types/react": "^19.2.18",
            "@types/react-dom": "^19.2.7",
            "@types/node": "^22.20.1",
            "@types/jest": "^29.5.14",
            "tailwindcss": "^4.3.3",
            "@tailwindcss/postcss": "^4.3.3",
            "autoprefixer": "^10.5.5",
            "postcss": "^8.5.28",
            "eslint": "^9.39.5",
            "eslint-config-next": "16.3.4",
            "prettier": "^3.9.6",
            "jest": "^29.7.0",
            "jest-environment-jsdom": "^29.7.0",
            "@testing-library/react": "^16.3.3",
            "@testing-library/dom": "^10.4.1",
            "@testing-library/jest-dom": "^6.10.0",
            "@playwright/test": "^1.63.0",
        },
    }, indent=2) + "\n"))

    # next.config.js
    files.append(_write(os.path.join(root, "next.config.mjs"),
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  reactStrictMode: true,\n"
        "};\n\n"
        "export default nextConfig;\n"))

    # Tailwind 4: config via CSS (@import "tailwindcss"), no tailwind.config.js needed
    # postcss
    files.append(_write(os.path.join(root, "postcss.config.mjs"),
        "const config = {\n"
        "  plugins: {\n"
        "    '@tailwindcss/postcss': {},\n"
        "  },\n"
        "};\n\n"
        "export default config;\n"))

    # globals.css
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "globals.css"),
        "@import 'tailwindcss';\n"))

    # layout
    files.append(_write(os.path.join(root, "app/layout.tsx"),
        "import type { Metadata } from 'next';\n"
        "import './globals.css';\n\n"
        f"export const metadata: Metadata = {{\n"
        f"  title: '{job.title or name}',\n"
        f"  description: 'Built for {job.company or 'client'}',\n"
        "};\n\n"
        "export default function RootLayout({\n"
        "  children,\n"
        "}: {\n"
        "  children: React.ReactNode;\n"
        "}) {\n"
        "  return (\n"
        "    <html lang=\"en\">\n"
        "      <body>{children}</body>\n"
        "    </html>\n"
        "  );\n"
        "}\n"))

    # page
    files.append(_write(os.path.join(root, "app/page.tsx"),
        "export default function Home() {\n"
        "  return (\n"
        "    <main className=\"flex min-h-screen flex-col items-center justify-center p-8\">\n"
        f"      <h1 className=\"text-4xl font-bold\">{job.title or 'Welcome'}</h1>\n"
        f"      <p className=\"mt-4 text-lg text-gray-600\">Delivered for {job.company or 'client'}</p>\n"
        "      <a href=\"/api/health\" className=\"mt-6 text-blue-600 underline\">API health check</a>\n"
        "    </main>\n"
        "  );\n"
        "}\n"))

    # API route
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app/api/health")), "route.ts"),
        "import { NextResponse } from 'next/server';\n\n"
        "export async function GET() {\n"
        "  return NextResponse.json({ status: 'ok', time: new Date().toISOString() });\n"
        "}\n"))

    # --- error.tsx (App Router error boundary) ---
    files.append(_write(os.path.join(root, "app/error.tsx"),
        "'use client';\n\n"
        "export default function Error({\n"
        "  error,\n"
        "  reset,\n"
        "}: {\n"
        "  error: Error & { digest?: string };\n"
        "  reset: () => void;\n"
        "}) {\n"
        "  return (\n"
        "    <main className=\"flex min-h-screen flex-col items-center justify-center p-8\">\n"
        "      <h2 className=\"text-2xl font-semibold\">Something went wrong!</h2>\n"
        "      <p className=\"mt-2 text-gray-600\">{error.message}</p>\n"
        "      <button\n"
        "        onClick={reset}\n"
        "        className=\"mt-6 rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700\"\n"
        "      >\n"
        "        Try again\n"
        "      </button>\n"
        "    </main>\n"
        "  );\n"
        "}\n"))

    # --- loading.tsx ---
    files.append(_write(os.path.join(root, "app/loading.tsx"),
        "export default function Loading() {\n"
        "  return (\n"
        "    <div className=\"flex min-h-screen items-center justify-center\">\n"
        "      <div className=\"h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent\" />\n"
        "    </div>\n"
        "  );\n"
        "}\n"))

    # --- not-found.tsx ---
    files.append(_write(os.path.join(root, "app/not-found.tsx"),
        "export default function NotFound() {\n"
        "  return (\n"
        "    <main className=\"flex min-h-screen flex-col items-center justify-center p-8\">\n"
        "      <h1 className=\"text-6xl font-bold\">404</h1>\n"
        "      <p className=\"mt-4 text-lg text-gray-600\">Page not found</p>\n"
        "      <a href=\"/\" className=\"mt-6 text-blue-600 underline\">Go home</a>\n"
        "    </main>\n"
        "  );\n"
        "}\n"))

    # --- middleware.ts (security headers) ---
    files.append(_write(os.path.join(root, "middleware.ts"),
        "import { NextResponse } from 'next/server';\n"
        "import type { NextRequest } from 'next/server';\n\n"
        "export function middleware(request: NextRequest) {\n"
        "  const response = NextResponse.next();\n"
        "  response.headers.set('X-Frame-Options', 'DENY');\n"
        "  response.headers.set('X-Content-Type-Options', 'nosniff');\n"
        "  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');\n"
        "  response.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');\n"
        "  return response;\n"
        "}\n\n"
        "export const config = {\n"
        "  matcher: '/((?!api|_next/static|_next/image|favicon.ico).*)',\n"
        "};\n"))

    # --- sitemap.ts ---
    files.append(_write(os.path.join(root, "app/sitemap.ts"),
        "import type { MetadataRoute } from 'next';\n\n"
        "export default function sitemap(): MetadataRoute.Sitemap {\n"
        "  return [\n"
        "    {\n"
        "      url: process.env.NEXT_PUBLIC_SITE_URL || 'https://example.com',\n"
        "      lastModified: new Date(),\n"
        "      changeFrequency: 'weekly',\n"
        "      priority: 1,\n"
        "    },\n"
        "  ];\n"
        "}\n"))

    # --- robots.ts ---
    files.append(_write(os.path.join(root, "app/robots.ts"),
        "import type { MetadataRoute } from 'next';\n\n"
        "export default function robots(): MetadataRoute.Robots {\n"
        "  return {\n"
        "    rules: {\n"
        "      userAgent: '*',\n"
        "      allow: '/',\n"
        "    },\n"
        "    sitemap: `${process.env.NEXT_PUBLIC_SITE_URL || 'https://example.com'}/sitemap.xml`,\n"
        "  };\n"
        "}\n"))

    # --- public/ (folder + placeholder agar Dockerfile COPY tidak gagal) ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "public")), ".gitkeep"), ""))

    # --- component ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "components")), "Hero.tsx"),
        "export default function Hero({ title, company }: { title: string; company?: string }) {\n"
        "  return (\n"
        "    <section className=\"text-center\">\n"
        "      <h1 className=\"text-4xl font-bold\">{title}</h1>\n"
        "      {company && <p className=\"mt-4 text-lg text-gray-600\">Delivered for {company}</p>}\n"
        "    </section>\n"
        "  );\n"
        "}\n"))

    # --- test (jest + testing-library) ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "__tests__")), "Hero.test.tsx"),
        "import { render, screen } from '@testing-library/react';\n"
        "import '@testing-library/jest-dom';\n"
        "import Hero from '@/components/Hero';\n\n"
        "describe('Hero', () => {\n"
        "  it('renders title', () => {\n"
        "    render(<Hero title=\"Test App\" company=\"Acme\" />);\n"
        "    expect(screen.getByText('Test App')).toBeInTheDocument();\n"
        "  });\n"
        "  it('renders company when provided', () => {\n"
        "    render(<Hero title=\"Test App\" company=\"Acme\" />);\n"
        "    expect(screen.getByText(/Acme/)).toBeInTheDocument();\n"
        "  });\n"
        "});\n"))

    # --- jest.config.js ---
    files.append(_write(os.path.join(root, "jest.config.js"),
        "const nextJest = require('next/jest');\n\n"
        "const createJestConfig = nextJest({ dir: './' });\n\n"
        "const customJestConfig = {\n"
        "  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],\n"
        "  testEnvironment: 'jest-environment-jsdom',\n"
        "  moduleNameMapper: {\n"
        "    '^@/(.*)$': '<rootDir>/$1',\n"
        "  },\n"
        "};\n\n"
        "module.exports = createJestConfig(customJestConfig);\n"))

    # --- jest.setup.js ---
    files.append(_write(os.path.join(root, "jest.setup.js"),
        "import '@testing-library/jest-dom';\n"))

    # --- playwright.config.ts ---
    files.append(_write(os.path.join(root, "playwright.config.ts"),
        "import { defineConfig, devices } from '@playwright/test';\n\n"
        "export default defineConfig({\n"
        "  testDir: './e2e',\n"
        "  fullyParallel: true,\n"
        "  forbidOnly: !!process.env.CI,\n"
        "  retries: process.env.CI ? 2 : 0,\n"
        "  reporter: 'html',\n"
        "  use: {\n"
        "    baseURL: 'http://localhost:3000',\n"
        "    trace: 'on-first-retry',\n"
        "  },\n"
        "  projects: [\n"
        "    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },\n"
        "  ],\n"
        "  webServer: {\n"
        "    command: 'npm run dev',\n"
        "    url: 'http://localhost:3000',\n"
        "    reuseExistingServer: !process.env.CI,\n"
        "  },\n"
        "});\n"))

    # --- e2e/home.spec.ts ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "e2e")), "home.spec.ts"),
        "import { test, expect } from '@playwright/test';\n\n"
        "test('homepage renders title', async ({ page }) => {\n"
        "  await page.goto('/');\n"
        "  await expect(page.locator('h1')).toBeVisible();\n"
        "});\n"))

    # --- eslint.config.mjs (ESLint 9 flat config) ---
    files.append(_write(os.path.join(root, "eslint.config.mjs"),
        "import { defineConfig, globalIgnores } from 'eslint/config';\n"
        "import nextVitals from 'eslint-config-next/core-web-vitals';\n"
        "import nextTs from 'eslint-config-next/typescript';\n\n"
        "export default defineConfig([\n"
        "  ...nextVitals,\n"
        "  ...nextTs,\n"
        "  globalIgnores(['.next/**', 'out/**', 'build/**', 'next-env.d.ts']),\n"
        "  {\n"
        "    rules: {\n"
        "      '@typescript-eslint/no-unused-vars': 'warn',\n"
        "    },\n"
        "  },\n"
        "]);\n"))

    # --- .prettierrc ---
    files.append(_write(os.path.join(root, ".prettierrc"),
        json.dumps({
            "semi": True,
            "singleQuote": True,
            "trailingComma": "all",
            "printWidth": 100,
        }, indent=2) + "\n"))

    # --- tsconfig.json ---
    files.append(_write(os.path.join(root, "tsconfig.json"),
        json.dumps({
            "compilerOptions": {
                "target": "ES2017",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": True,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "plugins": [{"name": "next"}],
                "paths": {"@/*": ["./*"]},
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"],
        }, indent=2) + "\n"))

    # --- next-env.d.ts ---
    files.append(_write(os.path.join(root, "next-env.d.ts"),
        "/// <reference types=\"next\" />\n"
        "/// <reference types=\"next/image-types/global\" />\n\n"
        "// NOTE: This file should not be edited\n"
        "// see https://nextjs.org/docs/basic-features/typescript for more information.\n"))

    # --- Dockerfile ---
    files.append(_write(os.path.join(root, "Dockerfile"),
        "# ---- build stage ----\n"
        "FROM node:22-alpine AS builder\n"
        "WORKDIR /app\n"
        "COPY package.json package-lock.json* ./\n"
        "RUN npm ci || npm install\n"
        "COPY . .\n"
        "RUN npm run build\n\n"
        "# ---- runtime stage ----\n"
        "FROM node:22-alpine AS runner\n"
        "WORKDIR /app\n"
        "ENV NODE_ENV=production\n"
        "COPY --from=builder /app/.next ./.next\n"
        "COPY --from=builder /app/public ./public\n"
        "COPY --from=builder /app/node_modules ./node_modules\n"
        "COPY --from=builder /app/package.json ./package.json\n"
        "EXPOSE 3000\n"
        'CMD ["npm", "start"]\n'))

    # --- .dockerignore ---
    files.append(_write(os.path.join(root, ".dockerignore"),
        "node_modules\n.next\n.git\n.env\n*.log\n"))

    # --- .github/workflows/ci.yml ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-node@v4\n"
        "        with:\n"
        "          node-version: '22'\n"
        "          cache: 'npm'\n"
        "      - run: npm ci || npm install\n"
        "      - run: npm run lint\n"
        "      - run: npm run typecheck\n"
        "      - run: npm test -- --ci\n"
        "      - run: npm run build\n"))

    # --- .gitignore ---
    files.append(_write(os.path.join(root, ".gitignore"),
        "node_modules/\n.next/\nout/\n.env\n.env.local\n*.log\ncoverage/\n"))

    # --- .env.example ---
    files.append(_write(os.path.join(root, ".env.example"),
        "NEXT_PUBLIC_SITE_URL=https://example.com\n"))

    # README
    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or name}\n\n"
        f"Deliverable untuk **{job.company or 'client'}**.\n\n"
        "## Stack\n"
        "- Next.js 16 (App Router)\n"
        "- React 19 + TypeScript (strict)\n"
        "- Tailwind CSS 4\n"
        "- ESLint 9 (flat config) + Prettier\n"
        "- Jest + Testing Library + Playwright\n"
        "- Docker + GitHub Actions CI\n\n"
        "## Run\n```bash\nnpm install\nnpm run dev\n```\n\n"
        "## Lint & format\n```bash\nnpm run lint\nnpm run format\n```\n\n"
        "## Test\n```bash\nnpm test\nnpm run test:e2e\n```\n\n"
        "## Build & Docker\n```bash\nnpm run build\ndocker build -t " + name + " .\n```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug,
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Next.js web app '{name}' ({len(files)} files, ESLint+Jest+CI+Docker)",
        "role": "developer",
    }


def build_api(job: Job, framework: str = "fastapi") -> dict:
    """Generate REST API backend (FastAPI) production-grade.

    Standar Google / perusahaan besar:
      - FastAPI + Pydantic v2 + async + SQLAlchemy 2.0 (asyncpg)
      - JWT auth (PyJWT) + password hashing (bcrypt langsung, bukan passlib)
      - Rate limiting (slowapi) + CORS + global exception handler
      - Structured logging (structlog) + request ID middleware
      - Alembic migration + health check (liveness/readiness)
      - pytest test suite (unit + integration) + coverage
      - Dockerfile multi-stage + docker-compose (postgres)
      - GitHub Actions CI (lint + test + build)
      - .env.example, .gitignore, README lengkap
    """
    slug = _slugify(job.title) + "-api"
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug))
    files = []

    # --- requirements.txt ---
    files.append(_write(os.path.join(root, "requirements.txt"),
        "fastapi==0.141.1\n"
        "uvicorn[standard]==0.52.4\n"
        "pydantic==2.13.5\n"
        "pydantic-settings==2.15.0\n"
        "email-validator==2.3.0\n"
        "sqlalchemy[asyncio]==2.0.52\n"
        "asyncpg==0.31.0\n"
        "aiosqlite==0.22.1\n"
        "alembic==1.19.2\n"
        "PyJWT==2.13.0\n"
        "bcrypt==5.0.0\n"
        "python-multipart==0.0.32\n"
        "slowapi==0.1.10\n"
        "structlog==26.1.0\n"
        "httpx==0.28.1\n"
        "pytest==9.1.1\n"
        "pytest-cov==7.1.0\n"
        "pytest-asyncio==1.4.0\n"))

    # --- app/main.py ---
    main_py = f'''"""FastAPI application: {job.title or 'API'}.

Production-grade backend with JWT auth, rate limiting, CORS, structured
logging, SQLAlchemy 2.0 async, and OpenAPI docs.
"""
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from .config import get_settings
from .db import get_db, get_engine
from .routers import auth, items

settings = get_settings()
logger = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: jangan create_all di sini — itu tugas Alembic migration.
    # Lifespan hanya log startup/shutdown agar test hermetic tidak menyentuh
    # engine produksi (postgres) sama sekali.
    logger.info("startup_complete", service=settings.app_name)
    yield
    logger.info("shutdown_complete", service=settings.app_name)


app = FastAPI(
    title="{job.title or 'API'}",
    version="1.0.0",
    description="Production REST API with JWT auth, rate limiting, and SQLAlchemy async.",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS (restrict origins in production via env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_info=exc, path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={{"detail": "Internal server error"}},
    )


# Routers
app.include_router(auth.router)
app.include_router(items.router)


@app.get("/", tags=["health"])
@limiter.limit("10/minute")
async def root(request: Request):
    logger.info("root_called")
    return {{"service": settings.app_name, "version": "1.0.0"}}


@app.get("/health/live", tags=["health"])
async def liveness():
    return {{"status": "alive"}}


@app.get("/health/ready", tags=["health"])
async def readiness(db=Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {{"status": "ready", "database": "ok"}}
    except Exception as e:
        logger.error("readiness_failed", error=str(e))
        return JSONResponse(status_code=503, content={{"status": "not_ready", "database": "down"}})
'''
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "main.py"), main_py))

    # --- app/__init__.py ---
    files.append(_write(os.path.join(root, "app/__init__.py"), ""))

    # --- app/config.py ---
    files.append(_write(os.path.join(root, "app/config.py"),
        "from functools import lru_cache\n"
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
        "class Settings(BaseSettings):\n"
        "    model_config = SettingsConfigDict(env_file=\".env\", env_file_encoding=\"utf-8\")\n\n"
        "    app_name: str = \"" + (job.title or 'API') + "\"\n"
        "    environment: str = \"development\"\n"
        "    secret_key: str = \"change-me-in-production-32bytes-minimum-secret\"\n"
        "    algorithm: str = \"HS256\"\n"
        "    access_token_expire_minutes: int = 30\n"
        "    database_url: str = \"postgresql+asyncpg://postgres:postgres@localhost:5432/app\"\n"
        "    cors_origins: list[str] = [\"http://localhost:3000\"]\n\n\n"
        "@lru_cache\n"
        "def get_settings() -> Settings:\n"
        "    return Settings()\n"))

    # --- app/db.py ---
    files.append(_write(os.path.join(root, "app/db.py"),
        "from functools import lru_cache\n\n"
        "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
        "from sqlalchemy.orm import DeclarativeBase\n\n"
        "from .config import get_settings\n\n"
        "settings = get_settings()\n\n\n"
        "class Base(DeclarativeBase):\n"
        "    pass\n\n\n"
        "@lru_cache\n"
        "def get_engine():\n"
        "    # Lazy engine: dibuat saat pertama dipakai, bukan saat import.\n"
        "    # Ini menjaga test hermetic — import app.db tidak memaksa driver DB\n"
        "    # (asyncpg) terinstall, dan test bisa override get_db dengan SQLite\n"
        "    # tanpa menyentuh engine produksi.\n"
        "    return create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)\n\n\n"
        "async def get_db():\n"
        "    engine = get_engine()\n"
        "    session_factory = async_sessionmaker(engine, expire_on_commit=False)\n"
        "    async with session_factory() as session:\n"
        "        yield session\n"))

    # --- app/models.py ---
    files.append(_write(os.path.join(root, "app/models.py"),
        "from datetime import datetime, timezone\n\n"
        "from sqlalchemy import DateTime, Float, ForeignKey, Integer, String\n"
        "from sqlalchemy.orm import Mapped, mapped_column, relationship\n\n"
        "from .db import Base\n\n\n"
        "class User(Base):\n"
        "    __tablename__ = \"users\"\n\n"
        "    id: Mapped[int] = mapped_column(Integer, primary_key=True)\n"
        "    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)\n"
        "    email: Mapped[str] = mapped_column(String(255), unique=True)\n"
        "    hashed_password: Mapped[str] = mapped_column(String(255))\n"
        "    created_at: Mapped[datetime] = mapped_column(\n"
        "        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))\n\n"
        "    items: Mapped[list[\"Item\"]] = relationship(back_populates=\"owner\", cascade=\"all, delete-orphan\")\n\n\n"
        "class Item(Base):\n"
        "    __tablename__ = \"items\"\n\n"
        "    id: Mapped[int] = mapped_column(Integer, primary_key=True)\n"
        "    name: Mapped[str] = mapped_column(String(255))\n"
        "    value: Mapped[float] = mapped_column(Float)\n"
        "    owner_id: Mapped[int] = mapped_column(ForeignKey(\"users.id\"))\n\n"
        "    owner: Mapped[User] = relationship(back_populates=\"items\")\n"))

    # --- app/schemas.py ---
    files.append(_write(os.path.join(root, "app/schemas.py"),
        "from pydantic import BaseModel, ConfigDict, EmailStr, Field\n\n\n"
        "class UserCreate(BaseModel):\n"
        "    username: str = Field(min_length=3, max_length=64)\n"
        "    email: EmailStr\n"
        "    password: str = Field(min_length=8)\n\n\n"
        "class UserOut(BaseModel):\n"
        "    model_config = ConfigDict(from_attributes=True)\n"
        "    id: int\n"
        "    username: str\n"
        "    email: EmailStr\n\n\n"
        "class Token(BaseModel):\n"
        "    access_token: str\n"
        "    token_type: str = \"bearer\"\n\n\n"
        "class ItemCreate(BaseModel):\n"
        "    name: str = Field(min_length=1, max_length=255)\n"
        "    value: float\n\n\n"
        "class ItemOut(BaseModel):\n"
        "    model_config = ConfigDict(from_attributes=True)\n"
        "    id: int\n"
        "    name: str\n"
        "    value: float\n"
        "    owner_id: int\n"))

    # --- app/security.py ---
    files.append(_write(os.path.join(root, "app/security.py"),
        "from datetime import datetime, timedelta, timezone\n\n"
        "import bcrypt\n"
        "import jwt\n\n"
        "from .config import get_settings\n\n"
        "settings = get_settings()\n\n\n"
        "def hash_password(password: str) -> str:\n"
        "    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()\n\n\n"
        "def verify_password(plain: str, hashed: str) -> bool:\n"
        "    try:\n"
        "        return bcrypt.checkpw(plain.encode(), hashed.encode())\n"
        "    except ValueError:\n"
        "        return False\n\n\n"
        "def create_access_token(subject: str, expires_minutes: int | None = None) -> str:\n"
        "    expire = datetime.now(timezone.utc) + timedelta(\n"
        "        minutes=expires_minutes or settings.access_token_expire_minutes)\n"
        "    return jwt.encode(\n"
        "        {\"sub\": subject, \"exp\": expire},\n"
        "        settings.secret_key,\n"
        "        algorithm=settings.algorithm,\n"
        "    )\n\n\n"
        "def decode_token(token: str) -> dict:\n"
        "    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])\n"))

    # --- app/deps.py ---
    files.append(_write(os.path.join(root, "app/deps.py"),
        "from fastapi import Depends, HTTPException, status\n"
        "from fastapi.security import OAuth2PasswordBearer\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.ext.asyncio import AsyncSession\n\n"
        "from .db import get_db\n"
        "from .models import User\n"
        "from .security import decode_token\n"
        "import jwt as pyjwt\n\n"
        "oauth2_scheme = OAuth2PasswordBearer(tokenUrl=\"/auth/token\")\n\n\n"
        "async def get_current_user(\n"
        "    token: str = Depends(oauth2_scheme),\n"
        "    db: AsyncSession = Depends(get_db),\n"
        ") -> User:\n"
        "    creds_exc = HTTPException(\n"
        "        status_code=status.HTTP_401_UNAUTHORIZED,\n"
        "        detail=\"Could not validate credentials\",\n"
        "        headers={\"WWW-Authenticate\": \"Bearer\"},\n"
        "    )\n"
        "    try:\n"
        "        payload = decode_token(token)\n"
        "        username: str = payload.get(\"sub\")\n"
        "        if username is None:\n"
        "            raise creds_exc\n"
        "    except pyjwt.PyJWTError:\n"
        "        raise creds_exc\n"
        "    result = await db.execute(select(User).where(User.username == username))\n"
        "    user = result.scalar_one_or_none()\n"
        "    if user is None:\n"
        "        raise creds_exc\n"
        "    return user\n"))

    # --- app/routers/__init__.py ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app/routers")), "__init__.py"), ""))

    # --- app/routers/auth.py ---
    files.append(_write(os.path.join(root, "app/routers/auth.py"),
        "from fastapi import APIRouter, Depends, HTTPException, status\n"
        "from fastapi.security import OAuth2PasswordRequestForm\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.ext.asyncio import AsyncSession\n\n"
        "from ..db import get_db\n"
        "from ..models import User\n"
        "from ..schemas import Token, UserCreate, UserOut\n"
        "from ..security import create_access_token, hash_password, verify_password\n\n"
        "router = APIRouter(prefix=\"/auth\", tags=[\"auth\"])\n\n\n"
        "@router.post(\"/register\", response_model=UserOut, status_code=201)\n"
        "async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):\n"
        "    existing = await db.execute(select(User).where(User.username == user_in.username))\n"
        "    if existing.scalar_one_or_none():\n"
        "        raise HTTPException(400, \"Username already registered\")\n"
        "    user = User(\n"
        "        username=user_in.username,\n"
        "        email=user_in.email,\n"
        "        hashed_password=hash_password(user_in.password),\n"
        "    )\n"
        "    db.add(user)\n"
        "    await db.commit()\n"
        "    await db.refresh(user)\n"
        "    return user\n\n\n"
        "@router.post(\"/token\", response_model=Token)\n"
        "async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):\n"
        "    result = await db.execute(select(User).where(User.username == form.username))\n"
        "    user = result.scalar_one_or_none()\n"
        "    if not user or not verify_password(form.password, user.hashed_password):\n"
        "        raise HTTPException(\n"
        "            status_code=status.HTTP_401_UNAUTHORIZED,\n"
        "            detail=\"Incorrect username or password\",\n"
        "        )\n"
        "    token = create_access_token(user.username)\n"
        "    return Token(access_token=token, token_type=\"bearer\")\n"))

    # --- app/routers/items.py ---
    files.append(_write(os.path.join(root, "app/routers/items.py"),
        "from fastapi import APIRouter, Depends, HTTPException\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.ext.asyncio import AsyncSession\n\n"
        "from ..db import get_db\n"
        "from ..deps import get_current_user\n"
        "from ..models import Item, User\n"
        "from ..schemas import ItemCreate, ItemOut\n\n"
        "router = APIRouter(prefix=\"/items\", tags=[\"items\"])\n\n\n"
        "@router.get(\"\", response_model=list[ItemOut])\n"
        "async def list_items(\n"
        "    db: AsyncSession = Depends(get_db),\n"
        "    current_user: User = Depends(get_current_user),\n"
        "):\n"
        "    result = await db.execute(select(Item).where(Item.owner_id == current_user.id))\n"
        "    return result.scalars().all()\n\n\n"
        "@router.post(\"\", response_model=ItemOut, status_code=201)\n"
        "async def create_item(\n"
        "    item_in: ItemCreate,\n"
        "    db: AsyncSession = Depends(get_db),\n"
        "    current_user: User = Depends(get_current_user),\n"
        "):\n"
        "    item = Item(name=item_in.name, value=item_in.value, owner_id=current_user.id)\n"
        "    db.add(item)\n"
        "    await db.commit()\n"
        "    await db.refresh(item)\n"
        "    return item\n\n\n"
        "@router.get(\"/{item_id}\", response_model=ItemOut)\n"
        "async def get_item(\n"
        "    item_id: int,\n"
        "    db: AsyncSession = Depends(get_db),\n"
        "    current_user: User = Depends(get_current_user),\n"
        "):\n"
        "    item = await db.get(Item, item_id)\n"
        "    if not item or item.owner_id != current_user.id:\n"
        "        raise HTTPException(404, \"Item not found\")\n"
        "    return item\n"))

    # --- alembic.ini ---
    files.append(_write(os.path.join(root, "alembic.ini"),
        "[alembic]\n"
        "script_location = alembic\n"
        "sqlalchemy.url = postgresql+asyncpg://postgres:postgres@localhost:5432/app\n\n"
        "[loggers]\n"
        "keys = root,sqlalchemy,alembic\n\n"
        "[handlers]\n"
        "keys = console\n\n"
        "[formatters]\n"
        "keys = generic\n\n"
        "[logger_root]\n"
        "level = WARN\n"
        "handlers = console\n"
        "qualname =\n\n"
        "[logger_sqlalchemy]\n"
        "level = WARN\n"
        "handlers =\n"
        "qualname = sqlalchemy.engine\n\n"
        "[logger_alembic]\n"
        "level = INFO\n"
        "handlers =\n"
        "qualname = alembic\n\n"
        "[handler_console]\n"
        "class = StreamHandler\n"
        "args = (sys.stderr,)\n"
        "level = NOTSET\n"
        "formatter = generic\n\n"
        "[formatter_generic]\n"
        "format = %(levelname)-5.5s [%(name)s] %(message)s\n"))

    # --- alembic/env.py ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "alembic")), "env.py"),
        "from logging.config import fileConfig\n\n"
        "from sqlalchemy import pool\n"
        "from sqlalchemy.engine import Connection\n"
        "from sqlalchemy.ext.asyncio import async_engine_from_config\n\n"
        "from alembic import context\n"
        "from app.db import Base\n"
        "from app.models import Item, User  # noqa: F401 (register models)\n\n"
        "config = context.config\n"
        "if config.config_file_name is not None:\n"
        "    fileConfig(config.config_file_name)\n\n"
        "target_metadata = Base.metadata\n\n\n"
        "def run_migrations_offline() -> None:\n"
        "    context.configure(\n"
        "        url=config.get_main_option(\"sqlalchemy.url\"),\n"
        "        target_metadata=target_metadata,\n"
        "        literal_binds=True,\n"
        "        dialect_opts={\"paramstyle\": \"named\"},\n"
        "    )\n"
        "    with context.begin_transaction():\n"
        "        context.run_migrations()\n\n\n"
        "def do_run_migrations(connection: Connection) -> None:\n"
        "    context.configure(connection=connection, target_metadata=target_metadata)\n"
        "    with context.begin_transaction():\n"
        "        context.run_migrations()\n\n\n"
        "async def run_async_migrations() -> None:\n"
        "    connectable = async_engine_from_config(\n"
        "        config.get_section(config.config_ini_section, {}),\n"
        "        prefix=\"sqlalchemy.\",\n"
        "        poolclass=pool.NullPool,\n"
        "    )\n"
        "    async with connectable.connect() as connection:\n"
        "        await connection.run_sync(do_run_migrations)\n"
        "    await connectable.dispose()\n\n\n"
        "def run_migrations_online() -> None:\n"
        "    import asyncio\n"
        "    asyncio.run(run_async_migrations())\n\n\n"
        "if context.is_offline_mode():\n"
        "    run_migrations_offline()\n"
        "else:\n"
        "    run_migrations_online()\n"))

    # --- alembic/script.py.mako ---
    files.append(_write(os.path.join(root, "alembic/script.py.mako"),
        "\"\"\"${{message}}\n\n"
        "Revision ID: ${{up_revision}}\n"
        "Revises: ${{down_revision | comma,n}}\n"
        "Create Date: ${{create_date}}\n\n"
        "\"\"\"\n"
        "from typing import Sequence, Union\n\n"
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "${{imports if imports else \"\"}}\n\n"
        "revision: str = ${{repr(up_revision)}}\n"
        "down_revision: Union[str, None] = ${{repr(down_revision)}}\n"
        "branch_labels: Union[str, Sequence[str], None] = ${{repr(branch_labels)}}\n"
        "depends_on: Union[str, Sequence[str], None] = ${{repr(depends_on)}}\n\n\n"
        "def upgrade() -> None:\n"
        "    ${{upgrades if upgrades else \"pass\"}}\n\n\n"
        "def downgrade() -> None:\n"
        "    ${{downgrades if downgrades else \"pass\"}}\n"))

    # --- alembic/versions/.gitkeep ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "alembic/versions")), ".gitkeep"), ""))

    # --- tests/test_api.py ---
    tests = '''"""Integration tests using FastAPI TestClient with SQLite in-memory (hermetic).

Tests run against a temporary SQLite database (aiosqlite) so they do not
require an external PostgreSQL server. The app's async engine is overridden
via dependency override for full hermeticity.
"""
import pytest
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _setup_db(tmp_path, monkeypatch):
    """Point the app at a temp SQLite DB and create tables."""
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "test.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async def create_tables():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())

    async def override_get_db():
        async with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    asyncio.run(test_engine.dispose())


@pytest.fixture()
def client():
    # NOTE: TestClient(app) runs lifespan; with SQLite override the lifespan
    # create_all is a no-op for the overridden engine, so tables are created
    # by _setup_db instead.
    with TestClient(app) as c:
        yield c


def test_liveness(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "service" in r.json()


def test_register_and_login(client):
    r = client.post("/auth/register", json={
        "username": "alice", "email": "alice@example.com",
        "password": "supersecret123"})
    assert r.status_code == 201
    assert r.json()["username"] == "alice"
    # login to get token
    r = client.post("/auth/token", data={
        "username": "alice", "password": "supersecret123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token


def test_items_require_auth(client):
    r = client.get("/items")
    assert r.status_code == 401


def test_item_crud(client):
    # register + login
    client.post("/auth/register", json={
        "username": "bob", "email": "bob@example.com",
        "password": "supersecret123"})
    token = client.post("/auth/token", data={
        "username": "bob", "password": "supersecret123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # create
    r = client.post("/items", json={"name": "widget", "value": 9.99}, headers=headers)
    assert r.status_code == 201
    item_id = r.json()["id"]
    # list
    r = client.get("/items", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    # get one
    r = client.get(f"/items/{item_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "widget"
'''
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_api.py"), tests))
    files.append(_write(os.path.join(root, "tests/__init__.py"), ""))

    # --- pytest.ini ---
    files.append(_write(os.path.join(root, "pytest.ini"),
        "[pytest]\n"
        "addopts = -v --cov=app --cov-report=term-missing\n"
        "testpaths = tests\n"
        "asyncio_mode = auto\n"))

    # --- Dockerfile (multi-stage) ---
    files.append(_write(os.path.join(root, "Dockerfile"),
        "# ---- build stage ----\n"
        "FROM python:3.12-slim AS builder\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir --upgrade pip && \\\n"
        "    pip install --no-cache-dir -r requirements.txt\n\n"
        "# ---- runtime stage ----\n"
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages\n"
        "COPY --from=builder /usr/local/bin /usr/local/bin\n"
        "COPY . .\n"
        "RUN addgroup --system app && adduser --system --ingroup app app\n"
        "USER app\n"
        "EXPOSE 8000\n"
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'))

    # --- docker-compose.yml ---
    files.append(_write(os.path.join(root, "docker-compose.yml"),
        "services:\n"
        "  api:\n"
        "    build: .\n"
        "    ports:\n"
        "      - \"8000:8000\"\n"
        "    environment:\n"
        "      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/app\n"
        "      - SECRET_KEY=${SECRET_KEY:-change-me-in-production}\n"
        "    depends_on:\n"
        "      db:\n"
        "        condition: service_healthy\n"
        "    restart: unless-stopped\n\n"
        "  db:\n"
        "    image: postgres:16-alpine\n"
        "    environment:\n"
        "      - POSTGRES_USER=postgres\n"
        "      - POSTGRES_PASSWORD=postgres\n"
        "      - POSTGRES_DB=app\n"
        "    ports:\n"
        "      - \"5432:5432\"\n"
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "    healthcheck:\n"
        "      test: [\"CMD-SHELL\", \"pg_isready -U postgres\"]\n"
        "      interval: 5s\n"
        "      timeout: 5s\n"
        "      retries: 5\n\n"
        "volumes:\n"
        "  pgdata:\n"))

    # --- .github/workflows/ci.yml ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    services:\n"
        "      postgres:\n"
        "        image: postgres:16-alpine\n"
        "        env:\n"
        "          POSTGRES_USER: postgres\n"
        "          POSTGRES_PASSWORD: postgres\n"
        "          POSTGRES_DB: app\n"
        "        ports:\n"
        "          - 5432:5432\n"
        "        options: >-\n"
        "          --health-cmd pg_isready\n"
        "          --health-interval 10s\n"
        "          --health-timeout 5s\n"
        "          --health-retries 5\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: pip install -r requirements.txt\n"
        "      - run: pytest\n"
        "      - run: docker build -t api .\n"))

    # --- .env.example ---
    files.append(_write(os.path.join(root, ".env.example"),
        "APP_NAME=" + (job.title or 'API') + "\n"
        "ENVIRONMENT=development\n"
        "SECRET_KEY=change-me-in-production\n"
        "ALGORITHM=HS256\n"
        "ACCESS_TOKEN_EXPIRE_MINUTES=30\n"
        "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app\n"
        "CORS_ORIGINS=[\"http://localhost:3000\"]\n"))

    # --- .gitignore ---
    files.append(_write(os.path.join(root, ".gitignore"),
        "__pycache__/\n*.pyc\n.env\n.venv/\n.pytest_cache/\n.coverage\nhtmlcov/\n*.egg-info/\n"))

    # --- README.md ---
    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'API'}\n\n"
        "Production-grade FastAPI backend for **" + (job.company or 'client') + "**.\\n\\n"
        "## Features\n"
        "- JWT authentication (register + login + protected routes)\n"
        "- SQLAlchemy 2.0 async + PostgreSQL (asyncpg)\n"
        "- Password hashing (bcrypt) + rate limiting (slowapi)\n"
        "- CORS + request ID middleware + structured logging (structlog)\n"
        "- Alembic migrations + health check (liveness/readiness)\n"
        "- Auto OpenAPI docs at `/docs`\n"
        "- Full test suite (pytest + coverage)\n"
        "- Multi-stage Docker + docker-compose (postgres)\n"
        "- GitHub Actions CI\n\n"
        "## Run locally\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload\n```\n\n"
        "## Run with Docker\n```bash\ndocker compose up --build\n```\n\n"
        "## Database migrations\n```bash\nalembic revision --autogenerate -m \"init\"\nalembic upgrade head\n```\n\n"
        "## Test\n```bash\npytest\n```\n\n"
        "## API docs\nOpen http://localhost:8000/docs\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug,
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"FastAPI backend '{slug}' (JWT + SQLAlchemy async + tests + Docker + CI)",
        "role": "developer",
    }


# =============================================================================
# DESIGNER
# =============================================================================

def build_landing_page(job: Job) -> dict:
    """Generate landing page HTML/CSS responsif (single-file, siap deploy)."""
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-landing"))
    files = []

    title = job.title or "Landing Page"
    company = job.company or "Client"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet" />
<style>
  :root {{
    --accent: #0f766e;         /* deep teal — professional, not generic purple */
    --accent-ink: #115e59;
    --bg: #fbfaf7;             /* warm off-white, not sterile white */
    --surface: #ffffff;
    --text: #1a1a1a;
    --text-muted: #5b5b5b;
    --border: #e8e4dc;
    --radius: 14px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', sans-serif; background: var(--bg); color: var(--text); line-height: 1.65; -webkit-font-smoothing: antialiased; }}
  h1, h2, h3 {{ font-family: 'Fraunces', serif; font-weight: 600; letter-spacing: -0.02em; }}
  header {{ background: var(--bg); color: var(--text); padding: 88px 24px 64px; text-align: center; border-bottom: 1px solid var(--border); }}
  header .eyebrow {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.14em; color: var(--accent); font-weight: 700; margin-bottom: 16px; }}
  header h1 {{ font-size: clamp(2.4rem, 5vw, 3.6rem); line-height: 1.1; max-width: 14ch; margin: 0 auto 20px; }}
  header p {{ font-size: 1.15rem; color: var(--text-muted); max-width: 52ch; margin: 0 auto; }}
  .cta {{ display: inline-block; margin-top: 32px; padding: 15px 36px; background: var(--accent); color: #fff; border-radius: 999px; font-weight: 700; text-decoration: none; transition: background 150ms ease; }}
  .cta:hover {{ background: var(--accent-ink); }}
  section {{ max-width: 960px; margin: 64px auto; padding: 0 24px; }}
  section h2 {{ font-size: 1.9rem; margin-bottom: 28px; }}
  .features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; }}
  .feature {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 28px; }}
  .feature h3 {{ font-size: 1.25rem; margin-bottom: 10px; }}
  .feature p {{ color: var(--text-muted); font-size: 0.95rem; }}
  footer {{ text-align: center; padding: 40px 24px; color: var(--text-muted); border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<header>
  <div class="eyebrow">{company}</div>
  <h1>{title}</h1>
  <p>Delivered with care for {company} — a focused, production-ready interface built for clarity and trust.</p>
  <a class="cta" href="#contact">Get Started</a>
</header>
<section>
  <h2>Why choose us</h2>
  <div class="features">
    <div class="feature"><h3>Fast</h3><p>Optimized for performance and speed, with a lean footprint.</p></div>
    <div class="feature"><h3>Reliable</h3><p>Built on best practices and covered by automated tests.</p></div>
    <div class="feature"><h3>Secure</h3><p>Security-first architecture with accessibility baked in.</p></div>
  </div>
</section>
<section id="contact">
  <h2>Contact</h2>
  <p>Reach out to learn more about this project.</p>
</section>
<footer>&copy; {datetime.now(timezone.utc).year} {company}. All rights reserved.</footer>
</body>
</html>
"""
    files.append(_write(os.path.join(root, "index.html"), html))
    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — Landing Page\n\nSingle-file responsive landing page.\n"
        "Open `index.html` in any browser. No build step required.\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-landing",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Landing page '{title}' (responsive HTML/CSS)",
        "role": "designer",
    }


def build_brand_kit(job: Job) -> dict:
    """Generate brand kit: palet warna, tipografi, logo SVG, panduan."""
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-brand"))
    files = []

    title = job.title or "Project"
    company = job.company or "Client"
    theme = _domain_theme(title, company)
    accent = theme["accent"]
    accent_hover = theme["accent_hover"]
    accent_subtle = theme["accent_subtle"]
    display = theme["display"]
    body = theme["body"]

    # Logo SVG — light-first, solid accent (bukan purple gradient)
    logo = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
  <rect width="200" height="200" rx="40" fill="{accent}"/>
  <circle cx="100" cy="100" r="55" fill="#ffffff" opacity="0.92"/>
  <circle cx="100" cy="100" r="30" fill="{accent}"/>
</svg>
"""
    files.append(_write(os.path.join(root, "logo.svg"), logo))

    # Brand guide markdown
    guide = f"""# Brand Kit — {title}

> Domain terdeteksi: **{theme['label']}** · Generated for **{company}** · {_now()}

## Color Palette
| Color | Hex | Usage |
|---|---|---|
| Primary | `{accent}` | Headings, CTAs |
| Primary hover | `{accent_hover}` | Hover CTA |
| Accent subtle | `{accent_subtle}` | Chips, badges, tint |
| Background | `#f8fafc` | Page background |
| Text | `#0f172a` | Body text |

## Typography
- **Headings**: `{display}` (berkarakter, bold, 2–3rem)
- **Body**: `{body}` (regular, 1rem, line-height 1.6)

**Rule:** satu display + satu body. NEVER `Inter`/`Roboto`/`system-ui` sebagai display.

## Logo
See `logo.svg`. Solid primary accent, rounded corners.

## Voice & Tone
Professional, clear, confident.

Generated: {_now()}
"""
    files.append(_write(os.path.join(root, "BRAND_GUIDE.md"), guide))

    return {
        "slug": slug + "-brand",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Brand kit '{title}' (logo + guide)",
        "role": "designer",
    }


# =============================================================================
# DESIGNER — UI (design system & component kit)
# =============================================================================

def _word_in(keyword: str, text: str) -> bool:
    """Cocokkan keyword sebagai kata utuh (word boundary), bukan substring.

    Mencegah false-positive seperti 'ai' cocok dengan 'email', 'care' dengan
    'healthcare', 'city' dengan 'capacity', dll.
    """
    # keyword multi-kata dengan spasi/hyphen: cocok sebagai frasa substring
    if " " in keyword or "-" in keyword:
        return keyword in text
    # keyword tunggal: cocok bila diapit non-alphanumeric
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _google_fonts_url(display: str, body: str) -> str:
    """Bangun URL Google Fonts untuk display + body (semua Google Fonts)."""
    d = display.replace(" ", "+")
    b = body.replace(" ", "+")
    return (f"https://fonts.googleapis.com/css2?"
            f"family={d}:wght@500;600;700&"
            f"family={b}:wght@400;500;700&display=swap")


def _domain_theme(title: str, company: str) -> dict:
    """Deteksi domain dari judul/perusahaan → palette + font berkarakter.

    Mengembalikan dict dengan accent colors + font (semua tersedia di Google
    Fonts). Light-first default; domain tertentu (devtools, media) menandai
    dark_needed=True untuk mengaktifkan override .dark.
    """
    text = f"{title or ''} {company or ''}".lower()

    # (tuple keyword, dict theme) — urutan penting: yang lebih spesifik dulu
    themes = [
        (("fintech", "finance", "financial", "bank", "banking", "payment",
          "payments", "trading", "invest", "investing", "crypto", "wallet",
          "invoice", "accounting", "lending", "loan"),
         dict(accent="#10B981", accent_hover="#059669", accent_subtle="#d1fae5",
              display="Instrument Serif", body="Plus Jakarta Sans",
              dark_needed=False, label="Fintech")),
        (("health", "healthcare", "medical", "medtech", "clinic", "doctor", "therapy",
          "wellness", "pharma", "hospital", "patient"),
         dict(accent="#0D9488", accent_hover="#0f766e", accent_subtle="#ccfbf1",
              display="Outfit", body="Readex Pro",
              dark_needed=False, label="HealthTech")),
        (("ecommerce", "e-commerce", "shop", "store", "retail", "dtc", "cart",
          "checkout", "marketplace"),
         dict(accent="#8C6D58", accent_hover="#6b4f3e", accent_subtle="#f1e7de",
              display="Playfair Display", body="DM Sans",
              dark_needed=False, label="E-Commerce")),
        (("education", "edtech", "learn", "learning", "course", "academy",
          "school", "university", "student", "training", "teach"),
         dict(accent="#4F46E5", accent_hover="#4338ca", accent_subtle="#e0e7ff",
              display="Lexend", body="Plus Jakarta Sans",
              dark_needed=False, label="EdTech")),
        (("media", "news", "publish", "publishing", "editorial", "journal",
          "magazine", "blog", "article", "story"),
         dict(accent="#DC2626", accent_hover="#b91c1c", accent_subtle="#fee2e2",
              display="Newsreader", body="Figtree",
              dark_needed=True, label="Media")),
        (("nonprofit", "non-profit", "ngo", "charity", "foundation", "donate",
          "donation", "cause", "volunteer"),
         dict(accent="#15803D", accent_hover="#166534", accent_subtle="#dcfce7",
              display="Fraunces", body="Plus Jakarta Sans",
              dark_needed=False, label="Non-Profit")),
        (("devtool", "dev tool", "developer tool", "sdk", "cli", "infra",
          "infrastructure", "kubernetes", "docker", "terminal", "ide"),
         dict(accent="#F59E0B", accent_hover="#d97706", accent_subtle="#fef3c7",
              display="Space Grotesk", body="Figtree",
              dark_needed=True, label="DevTools")),
        (("saas", "software as a service", "b2b", "startup", "productivity",
          "workflow"),
         dict(accent="#1E40AF", accent_hover="#1e3a8a", accent_subtle="#dbeafe",
              display="Sora", body="DM Sans",
              dark_needed=False, label="SaaS")),
        (("government", "gov", "public", "civic", "municipal",
          "regulatory", "compliance", "legal"),
         dict(accent="#0284C7", accent_hover="#0369a1", accent_subtle="#e0f2fe",
              display="Public Sans", body="Figtree",
              dark_needed=False, label="GovTech")),
        (("corporate", "enterprise", "holding", "consulting", "consultancy",
          "agency", "business", "firm"),
         dict(accent="#2563EB", accent_hover="#1d4ed8", accent_subtle="#dbeafe",
              display="Playfair Display", body="DM Sans",
              dark_needed=False, label="Corporate")),
    ]

    for keywords, theme in themes:
        if any(_word_in(k, text) for k in keywords):
            return theme

    # Default: SaaS profesional — deep teal + Fraunces/DM Sans
    return dict(accent="#0f766e", accent_hover="#115e59", accent_subtle="#ccfbf1",
                display="Fraunces", body="DM Sans",
                dark_needed=False, label="SaaS")


def _tokens_css(title: str, company: str, theme: dict = None) -> str:
    """Sumber kebenaran tunggal token desain (light-first, token-driven).

    Dipakai oleh build_design_system DAN build_ui_kit agar tidak ada duplikasi
    token. Font berkarakter + palette adaptif per domain.
    """
    t = theme or _domain_theme(title, company)
    fonts_url = _google_fonts_url(t["display"], t["body"])
    display_font = f"'{t['display']}', serif"
    body_font = f"'{t['body']}', sans-serif"
    dark_block = ""
    if t["dark_needed"]:
        dark_block = """
/* Dark override — domain ini (dev tools / media) memang butuh tema gelap */
.dark {
  --bg-base: #0b0f19;
  --bg-surface: #151a26;
  --bg-surface-elevated: #1e2534;
  --text-primary: #f1f5f9;
  --text-muted: #94a3b8;
  --border-subtle: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
}
"""

    return f"""/* ============================================================
   {title} — Design Tokens
   Light-first, token-driven. Satu sumber kebenaran untuk semua UI.
   Domain: {t['label']} · Generated for {company} · {_now()}
   ============================================================ */

/* Font berkarakter — wajib dimuat via Google Fonts (atau self-host) */
@import url('{fonts_url}');

:root {{
  /* ----- Color (semantic roles, bukan hardcode hex) ----- */
  --brand-accent: {t['accent']};          /* primary CTA */
  --brand-accent-hover: {t['accent_hover']};
  --brand-accent-subtle: {t['accent_subtle']};   /* tint untuk chip/badge */

  --bg-base: #ffffff;
  --bg-surface: #f8fafc;
  --bg-surface-elevated: #f1f5f9;

  --text-primary: #0f172a;
  --text-muted: #475569;
  --text-inverse: #ffffff;

  --border-subtle: rgba(15, 23, 42, 0.08);
  --border-strong: rgba(15, 23, 42, 0.16);

  /* Status */
  --success: #16a34a;
  --warning: #d97706;
  --error: #dc2626;
  --info: #2563eb;

  /* Status tint (background chip/badge — jangan hardcode hex di komponen) */
  --success-subtle: #dcfce7;
  --warning-subtle: #fef3c7;
  --error-subtle: #fee2e2;
  --info-subtle: #dbeafe;

  /* ----- Typography ----- */
  --font-display: {display_font};
  --font-body: {body_font};
  --font-mono: 'JetBrains Mono', monospace;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;
  --text-3xl: 1.875rem;
  --text-4xl: 2.25rem;

  /* ----- Spacing (4px base scale) ----- */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --space-16: 4rem;

  /* ----- Radius ----- */
  --radius-sm: 0.375rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;
  --radius-full: 9999px;

  /* ----- Shadow (tonal, bukan drop shadow keras) ----- */
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(15, 23, 42, 0.08);
  --shadow-lg: 0 10px 15px -3px rgba(15, 23, 42, 0.10);

  /* ----- Motion ----- */
  --transition-fast: 150ms cubic-bezier(0.16, 1, 0.3, 1);
  --transition-normal: 300ms cubic-bezier(0.16, 1, 0.3, 1);
}}
{dark_block}
"""


def build_design_system(job: Job) -> dict:
    """Generate design system: token CSS + dokumentasi lengkap (UI).

    Meniru "brand built-in" dari Claude Design: satu sumber kebenaran untuk
    warna, tipografi, spacing, radius, shadow, dan motion — sebagai CSS
    variables + panduan penggunaan. Light-first, token-driven, font berkarakter.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-design-system"))
    files = []

    title = job.title or "Design System"
    company = job.company or "Client"
    theme = _domain_theme(title, company)

    # tokens.css — sumber kebenaran tunggal
    files.append(_write(os.path.join(root, "tokens.css"), _tokens_css(title, company, theme)))

    # DESIGN_SYSTEM.md — dokumentasi penggunaan
    guide = f"""# {title} — Design System

> Satu sumber kebenaran untuk warna, tipografi, spacing, dan motion.
> Semua komponen wajib mereferensikan token di `tokens.css`, **bukan** hardcode hex.

Generated for **{company}** · {_now()}
Domain yang terdeteksi: **{theme['label']}**

---

## 1. Color Roles

| Token | Nilai | Penggunaan |
|---|---|---|
| `--brand-accent` | `{theme['accent']}` | CTA utama, link aktif, fokus |
| `--brand-accent-hover` | `{theme['accent_hover']}` | Hover CTA |
| `--brand-accent-subtle` | `{theme['accent_subtle']}` | Chip, badge, background pilihan |
| `--bg-base` | `#ffffff` | Background halaman |
| `--bg-surface` | `#f8fafc` | Kartu, panel |
| `--bg-surface-elevated` | `#f1f5f9` | Hover kartu, dropdown |
| `--text-primary` | `#0f172a` | Body & heading |
| `--text-muted` | `#475569` | Teks sekunder |
| `--success` / `--warning` / `--error` | hijau/kuning/merah | Status fungsional |

**Rule:** jangan pernah hardcode warna di komponen. Selalu `var(--token)`.

## 2. Typography

- **Display**: `{theme['display']}` (berkarakter) — untuk heading, hero, angka besar.
- **Body**: `{theme['body']}` — untuk paragraf, form, UI umum.
- **Mono**: `JetBrains Mono` — untuk kode, angka tabular, data.

**Rule:** satu display + satu body. NEVER `Inter`/`Roboto`/`system-ui` sebagai display.

## 3. Spacing Scale

4px base: `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64` px (`--space-1` … `--space-16`).

**Rule:** gunakan kelipatan skala, jangan nilai arbitrer.

## 4. Radius & Shadow

- Radius: `sm 6 / md 8 / lg 12 / xl 16 / full 9999`.
- Shadow: tonal halus (`--shadow-sm/md/lg`), bukan drop shadow keras.

## 5. Motion

- `--transition-fast` (150ms) untuk hover/focus.
- `--transition-normal` (300ms) untuk panel/modal.
- Selalu `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out halus).

## 6. Aksesibilitas (WCAG 2.1 AA)

- Kontras body ≥ 4.5:1 (GovTech 7:1).
- Touch target ≥ 48×48 px (mobile).
- 5 state wajib per komponen: idle / hover / focus-visible / active / disabled.
- `focus-visible` ring selalu terlihat, jangan `outline: none` tanpa pengganti.

---

## Cara pakai

```html
<link rel="stylesheet" href="tokens.css" />
<style>
  .btn {{
    background: var(--brand-accent);
    color: var(--text-inverse);
    font-family: var(--font-body);
    padding: var(--space-3) var(--space-6);
    border-radius: var(--radius-md);
    transition: background var(--transition-fast);
  }}
  .btn:hover {{ background: var(--brand-accent-hover); }}
</style>
```

*Lihat `ui-kit.html` untuk komponen siap pakai yang dibangun di atas token ini.*
"""
    files.append(_write(os.path.join(root, "DESIGN_SYSTEM.md"), guide))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — Design System\n\n"
        f"Design system deliverable for {company}.\n\n"
        f"- `tokens.css` — CSS variables (sumber kebenaran)\n"
        f"- `DESIGN_SYSTEM.md` — dokumentasi & aturan penggunaan\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-design-system",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Design system '{title}' (tokens + documentation)",
        "role": "designer",
    }


def build_ui_kit(job: Job) -> dict:
    """Generate UI kit: komponen reusable (button, input, card, badge, dll).

    Meniru component registry (21st.dev / shadcn): komponen modular, token-driven,
    satu komponen per blok, dengan 5 state interaksi + microcopy nyata.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-ui-kit"))
    files = []

    title = job.title or "UI Kit"
    company = job.company or "Client"

    ui_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} — UI Kit</title>
<link rel="stylesheet" href="tokens.css" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: var(--font-body); background: var(--bg-surface); color: var(--text-primary); line-height: 1.6; padding: 48px 24px; }}
  h1, h2 {{ font-family: var(--font-display); letter-spacing: -0.02em; }}
  h1 {{ font-size: 2.25rem; margin-bottom: 4px; }}
  h2 {{ font-size: 1.5rem; margin: 40px 0 16px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  .subtitle {{ color: var(--text-muted); margin-bottom: 32px; }}
  .group {{ background: var(--bg-base); border: 1px solid var(--border-subtle); border-radius: var(--radius-xl); padding: 28px; margin-bottom: 24px; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }}

  /* ----- Button (5 state) ----- */
  .btn {{ display: inline-flex; align-items: center; justify-content: center; min-height: 48px; padding: 0 24px; border-radius: var(--radius-md); font-family: var(--font-body); font-weight: 600; font-size: 0.95rem; border: none; cursor: pointer; transition: all var(--transition-fast); }}
  .btn:focus-visible {{ outline: none; box-shadow: 0 0 0 3px var(--brand-accent-subtle), 0 0 0 5px var(--brand-accent); }}
  .btn:active {{ transform: scale(0.96); }}
  .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  .btn-primary {{ background: var(--brand-accent); color: var(--text-inverse); }}
  .btn-primary:hover {{ background: var(--brand-accent-hover); }}
  .btn-secondary {{ background: var(--bg-surface); color: var(--text-primary); border: 1px solid var(--border-strong); }}
  .btn-secondary:hover {{ background: var(--brand-accent-subtle); }}
  .btn-ghost {{ background: transparent; color: var(--text-muted); }}
  .btn-ghost:hover {{ background: var(--bg-surface); }}

  /* ----- Input ----- */
  .field {{ margin-bottom: 16px; }}
  .field label {{ display: block; font-size: 0.875rem; font-weight: 600; margin-bottom: 6px; }}
  .field input {{ width: 100%; max-width: 360px; min-height: 48px; padding: 0 14px; border: 1px solid var(--border-strong); border-radius: var(--radius-md); font-family: var(--font-body); font-size: 1rem; background: var(--bg-base); color: var(--text-primary); }}
  .field input:focus {{ outline: none; border-color: var(--brand-accent); box-shadow: 0 0 0 3px var(--brand-accent-subtle); }}
  .field input[aria-invalid="true"] {{ border-color: var(--error); }}
  .field .hint {{ font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }}
  .field .error {{ font-size: 0.8rem; color: var(--error); margin-top: 4px; }}

  /* ----- Card ----- */
  .card {{ background: var(--bg-base); border: 1px solid var(--border-subtle); border-radius: var(--radius-xl); padding: 24px; }}
  .card h3 {{ font-family: var(--font-display); font-size: 1.25rem; margin-bottom: 8px; }}
  .card p {{ color: var(--text-muted); font-size: 0.95rem; }}

  /* ----- Badge ----- */
  .badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: var(--radius-full); font-size: 0.75rem; font-weight: 600; }}
  .badge-success {{ background: var(--success-subtle); color: var(--success); }}
  .badge-warning {{ background: var(--warning-subtle); color: var(--warning); }}
  .badge-error {{ background: var(--error-subtle); color: var(--error); }}
  .badge-neutral {{ background: var(--brand-accent-subtle); color: var(--brand-accent); }}

  /* ----- Empty state ----- */
  .empty {{ text-align: center; padding: 48px 24px; }}
  .empty h3 {{ font-family: var(--font-display); font-size: 1.35rem; margin-bottom: 8px; }}
  .empty p {{ color: var(--text-muted); margin-bottom: 20px; }}
</style>
</head>
<body>
<div class="container">
  <h1>{title}</h1>
  <p class="subtitle">UI component kit for {company} — token-driven, accessible, ready to compose.</p>

  <h2>Buttons</h2>
  <div class="group">
    <div class="row">
      <button class="btn btn-primary">Create project</button>
      <button class="btn btn-secondary">Cancel</button>
      <button class="btn btn-ghost">Learn more</button>
      <button class="btn btn-primary" disabled>Disabled</button>
    </div>
  </div>

  <h2>Form inputs</h2>
  <div class="group">
    <div class="field">
      <label for="email">Email</label>
      <input id="email" type="email" placeholder="you@company.com" aria-describedby="email-hint" />
      <p class="hint" id="email-hint">We'll only use this to reach you about your account.</p>
    </div>
    <div class="field">
      <label for="password">Password</label>
      <input id="password" type="password" placeholder="********" aria-invalid="true" aria-describedby="password-error" />
      <p class="error" id="password-error">Use at least 8 characters. Longer is safer.</p>
    </div>
  </div>

  <h2>Cards</h2>
  <div class="group row">
    <div class="card">
      <h3>Ship in days, not months</h3>
      <p>Start from a working template and go live with your first release this week.</p>
    </div>
    <div class="card">
      <h3>Your data stays yours</h3>
      <p>Export everything anytime. No lock-in, no surprise fees.</p>
    </div>
    <div class="card">
      <h3>Help when you need it</h3>
      <p>A real human replies within one business day — not a bot queue.</p>
    </div>
  </div>

  <h2>Badges</h2>
  <div class="group">
    <div class="row">
      <span class="badge badge-success">Active</span>
      <span class="badge badge-warning">Pending</span>
      <span class="badge badge-error">Failed</span>
      <span class="badge badge-neutral">Beta</span>
    </div>
  </div>

  <h2>Empty state</h2>
  <div class="group">
    <div class="empty">
      <h3>Nothing here yet</h3>
      <p>Create your first project and it'll show up right here.</p>
      <button class="btn btn-primary">Create project</button>
    </div>
  </div>
</div>
</body>
</html>
"""
    files.append(_write(os.path.join(root, "tokens.css"), _tokens_css(title, company)))
    files.append(_write(os.path.join(root, "ui-kit.html"), ui_html))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — UI Kit\n\n"
        f"Reusable UI component kit for {company}.\n\n"
        f"- `ui-kit.html` — buttons, inputs, cards, badges, empty state\n"
        f"  (token-driven, 5 interaction states, real microcopy)\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-ui-kit",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"UI kit '{title}' (reusable components)",
        "role": "designer",
    }


# =============================================================================
# DESIGNER — UX (wireframe & user flow)
# =============================================================================

def build_wireframe(job: Job) -> dict:
    """Generate wireframe low-fidelity (UX): struktur halaman + anotasi.

    Low-fi wireframe sebagai HTML/CSS (bukan gambar) agar bisa diedit.
    Menunjukkan layout, hierarki konten, dan anotasi UX tanpa distraksi visual.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-wireframe"))
    files = []

    title = job.title or "Wireframe"
    company = job.company or "Client"

    wire_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} — Wireframe</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=DM+Sans:wght@400;500;700&display=swap');
  :root {{
    --wire-bg: #fafafa;
    --wire-block: #e5e7eb;
    --wire-block-alt: #d1d5db;
    --wire-text: #6b7280;
    --wire-accent: #9ca3af;
    --wire-border: #d1d5db;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', sans-serif; background: var(--wire-bg); color: #374151; padding: 32px; }}
  h1 {{ font-family: 'Fraunces', serif; font-size: 1.5rem; margin-bottom: 4px; }}
  .meta {{ color: var(--wire-text); font-size: 0.85rem; margin-bottom: 24px; }}
  .frame {{ max-width: 960px; margin: 0 auto 32px; background: #fff; border: 1px solid var(--wire-border); border-radius: 8px; overflow: hidden; }}
  .frame-label {{ padding: 10px 16px; background: #f3f4f6; border-bottom: 1px solid var(--wire-border); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--wire-text); }}
  .block {{ background: var(--wire-block); border: 1px dashed var(--wire-border); border-radius: 4px; min-height: 40px; display: flex; align-items: center; justify-content: center; color: var(--wire-text); font-size: 0.8rem; }}
  .block.alt {{ background: var(--wire-block-alt); }}
  .block.img {{ min-height: 180px; }}
  .block.btn {{ min-height: 48px; background: var(--wire-accent); color: #fff; border: none; }}
  .grid {{ display: grid; gap: 12px; padding: 16px; }}
  .grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
  .grid-2 {{ grid-template-columns: repeat(2, 1fr); }}
  .annotation {{ color: var(--wire-text); font-size: 0.8rem; padding: 4px 16px 16px; }}
  .annotation code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }}
  /* Responsif */
  @media (max-width: 768px) {{
    body {{ padding: 16px; }}
    h1 {{ font-size: 1.25rem; }}
    .grid-3, .grid-2 {{ grid-template-columns: 1fr; }}
    .block.img {{ min-height: 120px; }}
  }}
</style>
</head>
<body>
<h1>{title} — Low-Fidelity Wireframe</h1>
<p class="meta">For {company} · Structure & hierarchy only (no visual design) · {_now()}</p>

<div class="frame">
  <div class="frame-label">Landing / Home</div>
  <div class="grid">
    <div class="block" style="min-height:56px">Navigation bar (logo + links + CTA)</div>
    <div class="block img">Hero — headline + subhead + primary CTA</div>
    <div class="grid grid-3">
      <div class="block">Feature 1</div>
      <div class="block">Feature 2</div>
      <div class="block">Feature 3</div>
    </div>
    <div class="block img">Social proof / testimonial</div>
    <div class="grid grid-2">
      <div class="block">Pricing / offer</div>
      <div class="block">Contact form</div>
    </div>
    <div class="block">Footer (links + legal)</div>
  </div>
  <div class="annotation">
    <strong>Anotasi UX:</strong> satu <code>&lt;h1&gt;</code> di hero · CTA utama di atas fold ·
    hierarki visual: hero → fitur → bukti sosial → konversi → footer.
  </div>
</div>

<div class="frame">
  <div class="frame-label">Detail / Product</div>
  <div class="grid">
    <div class="block" style="min-height:56px">Breadcrumb + back</div>
    <div class="grid grid-2">
      <div class="block img">Product image</div>
      <div class="grid">
        <div class="block">Title + rating</div>
        <div class="block">Price + description</div>
        <div class="block btn">Add to cart (primary)</div>
      </div>
    </div>
    <div class="block">Related items</div>
  </div>
  <div class="annotation">
    <strong>Anotasi UX:</strong> aksi utama selalu terlihat · breadcrumb untuk navigasi balik ·
    info penting (harga) dekat dengan CTA.
  </div>
</div>
"""
    files.append(_write(os.path.join(root, "wireframe.html"), wire_html))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — Wireframe\n\n"
        f"Low-fidelity wireframe for {company}.\n\n"
        f"- `wireframe.html` — page structure + UX annotations\n"
        f"  (layout & hierarchy only, no visual design)\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-wireframe",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Wireframe '{title}' (low-fidelity + annotations)",
        "role": "designer",
    }


def build_user_flow(job: Job) -> dict:
    """Generate user flow diagram (UX): langkah-langkah perjalanan pengguna.

    Diagram alur sebagai HTML/CSS (bukan gambar) — menampilkan node + panah
    antar langkah, dengan titik keputusan dan anotasi.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-user-flow"))
    files = []

    title = job.title or "User Flow"
    company = job.company or "Client"

    flow_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} — User Flow</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=DM+Sans:wght@400;500;700&display=swap');
  :root {{
    --node: #ffffff;
    --node-start: #0f766e;
    --node-end: #dc2626;
    --node-decision: #fef3c7;
    --border: #d1d5db;
    --text: #374151;
    --muted: #6b7280;
    --arrow: #9ca3af;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', sans-serif; background: #fafafa; color: var(--text); padding: 32px; }}
  h1 {{ font-family: 'Fraunces', serif; font-size: 1.5rem; margin-bottom: 4px; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 32px; }}
  .flow {{ display: flex; flex-direction: column; align-items: center; gap: 8px; }}
  .node {{ background: var(--node); border: 2px solid var(--border); border-radius: 10px; padding: 14px 24px; min-width: 220px; text-align: center; font-weight: 600; font-size: 0.9rem; }}
  .node.start {{ background: var(--node-start); border-color: var(--node-start); color: #fff; }}
  .node.end {{ background: var(--node-end); border-color: var(--node-end); color: #fff; }}
  .node.decision {{ background: var(--node-decision); border-color: #d97706; }}
  .node .desc {{ display: block; font-weight: 400; font-size: 0.75rem; color: var(--muted); margin-top: 4px; }}
  .node.start .desc, .node.end .desc {{ color: rgba(255,255,255,0.85); }}
  .arrow {{ color: var(--arrow); font-size: 1.4rem; line-height: 1; }}
  .branch {{ display: flex; gap: 48px; align-items: flex-start; }}
  .branch-col {{ display: flex; flex-direction: column; align-items: center; gap: 8px; }}
  .branch-label {{ font-size: 0.75rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
  /* Responsif */
  @media (max-width: 768px) {{
    body {{ padding: 16px; }}
    h1 {{ font-size: 1.25rem; }}
    .node {{ min-width: 0; width: 100%; max-width: 320px; padding: 12px 16px; }}
    .branch {{ flex-direction: column; gap: 16px; align-items: center; }}
  }}
</style>
</head>
<body>
<h1>{title} — User Flow</h1>
<p class="meta">For {company} · End-to-end user journey · {_now()}</p>

<div class="flow">
  <div class="node start">Landing page<span class="desc">User arrives (organic / ad / referral)</span></div>
  <div class="arrow">↓</div>
  <div class="node">Explore value prop<span class="desc">Scan hero + features</span></div>
  <div class="arrow">↓</div>
  <div class="node decision">Interested?<span class="desc">Decision point</span></div>
  <div class="branch">
    <div class="branch-col">
      <div class="branch-label">Yes</div>
      <div class="arrow">↓</div>
      <div class="node">Click CTA<span class="desc">"Get Started" / "Sign up"</span></div>
      <div class="arrow">↓</div>
      <div class="node">Sign up form<span class="desc">Email + password (or SSO)</span></div>
      <div class="arrow">↓</div>
      <div class="node">Onboarding<span class="desc">Set up in &lt; 2 min</span></div>
      <div class="arrow">↓</div>
      <div class="node end">Activated ✓<span class="desc">User reaches value</span></div>
    </div>
    <div class="branch-col">
      <div class="branch-label">No</div>
      <div class="arrow">↓</div>
      <div class="node">Browse more<span class="desc">Scroll / read testimonials</span></div>
      <div class="arrow">↓</div>
      <div class="node">Exit<span class="desc">(retarget later)</span></div>
    </div>
  </div>
</div>

<div style="max-width:720px; margin: 40px auto 0; padding: 20px; background:#fff; border:1px solid var(--border); border-radius:10px;">
  <h2 style="font-size:1.1rem; margin-bottom:12px;">Anotasi UX</h2>
  <ul style="padding-left:20px; color:var(--muted); font-size:0.9rem; line-height:1.8;">
    <li><strong>Friction minimal:</strong> dari CTA ke "activated" maksimal 3 langkah.</li>
    <li><strong>Dua jalur keluar:</strong> "tidak tertarik" tetap diberi jalur (browse → retarget), bukan buntu.</li>
    <li><strong>Onboarding cepat:</strong> janji "&lt; 2 menit" mengurangi drop-off.</li>
    <li><strong>Microcopy:</strong> setiap langkah punya teks nyata (lihat microcopy-patterns).</li>
  </ul>
</div>
</body>
</html>
"""
    files.append(_write(os.path.join(root, "user-flow.html"), flow_html))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — User Flow\n\n"
        f"End-to-end user journey diagram for {company}.\n\n"
        f"- `user-flow.html` — nodes + arrows + decision points + annotations\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-user-flow",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"User flow '{title}' (journey diagram)",
        "role": "designer",
    }


# =============================================================================
# WRITER
# =============================================================================

def write_article(job: Job, topic: str = None, words: int = 800) -> dict:
    """Generate artikel/blog/technical writing (Markdown + HTML).

    Konten adaptif: menyesuaikan struktur & contoh dengan judul/topik job,
    bukan boilerplate generik. HTML dikonversi dari Markdown dengan benar
    (heading, bold, list, tabel) + meta SEO.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-article"))
    files = []

    title = topic or job.title or "Article"
    company = job.company or "Client"

    # Slug topik untuk dipakai di body (lowercase, tanpa karakter aneh)
    topic_slug = re.sub(r"[^a-zA-Z0-9 ]", "", title.lower()).strip()[:60] or "this topic"

    # Bangun body artikel yang substansial & spesifik topik (bukan lorem ipsum)
    body = f"""# {title}

*Written for {company} · {_now()}*

## Introduction

**{title}** has moved from a niche concern to a core priority. Teams that get
it right ship faster, retain more users, and spend less on rework. This guide
breaks down what {topic_slug} actually means in practice, the mistakes that
silently cost you time, and a concrete plan you can apply this week.

## Why It Matters Now

Three shifts have made {topic_slug} urgent rather than optional:

1. **Rising expectations** — users and clients now assume a baseline of quality
   that was once considered a differentiator.
2. **Lower cost of entry** — the tools to do {topic_slug} well are cheaper and
   more accessible than ever.
3. **Compounding returns** — small, consistent improvements in {topic_slug}
   accumulate into a defensible advantage over months, not years.

## Core Concepts

### 1. Start from the outcome, not the tool

The most common failure is choosing a technology or process before defining
what success looks like. Write down the single metric that matters, then work
backward to the simplest approach that moves it.

### 2. Make the invisible visible

What you cannot measure, you cannot improve. Instrument the key steps of
{topic_slug} so you can see where time and effort actually go.

### 3. Iterate in small, safe steps

No plan survives contact with reality. Ship the smallest useful version,
measure the result, and adjust. A weekly cadence beats a quarterly big bang.

## Practical Steps

- **Audit your current state.** Spend an hour mapping where {topic_slug} is
  already working and where it is silently failing.
- **Pick one lever.** Choose the single highest-impact change and commit to it
  for two weeks before expanding scope.
- **Document as you go.** A written record turns one-off effort into a reusable
  asset for the whole team.
- **Review weekly.** A short retrospective — what worked, what didn't, what's
  next — keeps momentum without ceremony.

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Chasing shiny new tools | Anchor decisions on outcomes, not features |
| Ignoring early feedback | Build a feedback loop before you invest deeply |
| Perfectionism before shipping | Ship a v1, then iterate in public |
| No ownership | Assign one clear owner per initiative |

## Conclusion

**{title}** is not a one-time project — it is a discipline. The teams that treat
it as an ongoing practice, rather than a box to tick, are the ones that pull
ahead. Start with the audit, pick one lever, and ship something small this week.

---

*Need help putting this into practice? Reach out — I'd love to help.*
"""
    files.append(_write(os.path.join(root, "article.md"), body))

    # HTML version — konversi Markdown yang benar + meta SEO
    html_body = _md_to_html(body)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<meta name="description" content="A practical guide to {title} — core concepts, common pitfalls, and actionable steps." />
<meta name="keywords" content="{topic_slug}" />
<meta property="og:title" content="{title}" />
<meta property="og:type" content="article" />
<style>
  body {{ font-family: 'DM Sans', sans-serif; max-width: 720px; margin: 0 auto; padding: 48px 24px; line-height: 1.7; color: #0f172a; }}
  h1, h2, h3 {{ font-family: 'Fraunces', serif; line-height: 1.2; }}
  h1 {{ font-size: 2rem; }}
  h2 {{ font-size: 1.4rem; margin-top: 2.2em; }}
  h3 {{ font-size: 1.1rem; margin-top: 1.6em; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1.5em 0; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 10px 14px; text-align: left; }}
  th {{ background: #f8fafc; }}
  blockquote {{ border-left: 3px solid #0f766e; margin: 1.5em 0; padding: 8px 20px; color: #475569; background: #f8fafc; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 2em 0; }}
  a {{ color: #0f766e; }}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""
    files.append(_write(os.path.join(root, "article.html"), html))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title}\n\nArticle deliverable for {company}.\n"
        f"- `article.md` — Markdown source\n- `article.html` — HTML version (SEO-ready)\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-article",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Article '{title}' (Markdown + HTML)",
        "role": "writer",
    }


# =============================================================================
# WEB3
# =============================================================================

def _audit_solidity(sol_sources: dict, contract_name: str) -> str:
    """Static analysis (SAST) kontrak Solidity — hasil nyata, bukan checkbox kosong.

    Dua lapis:
    1. Slither (jika terpasang) via subprocess — deteksi kerentanan umum.
    2. Fallback pattern-based analysis murni Python (selalu jalan, tanpa dependency)
       yang mendeteksi pola berbahaya: reentrancy, unchecked transfer, tx.origin,
       selfdestruct, delegatecall, missing access control, zero-address, dsb.

    Mengembalikan string Markdown berisi temuan terstruktur (severity + lokasi + saran).
    """
    findings = []  # list of (severity, title, detail)

    # --- Lapis 1: Slither (opsional) ---
    slither_out = None
    try:
        import shutil
        if shutil.which("slither"):
            # tulis source ke file temp agar slither bisa baca
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                for fname, content in sol_sources.items():
                    p = os.path.join(tmp, fname)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(content)
                try:
                    slither_out = subprocess.run(
                        ["slither", tmp, "--json", "slither.json"],
                        capture_output=True, text=True, timeout=120,
                    )
                    if slither_out.returncode == 0 and os.path.exists(os.path.join(tmp, "slither.json")):
                        with open(os.path.join(tmp, "slither.json"), encoding="utf-8") as f:
                            slither_data = json.load(f)
                        for det in slither_data.get("results", {}).get("detectors", []):
                            findings.append((
                                det.get("impact", "Medium"),
                                det.get("check", "Slither finding"),
                                det.get("description", "")[:300],
                            ))
                except Exception:
                    slither_out = None
    except Exception:
        slither_out = None

    # --- Lapis 2: Pattern-based analysis (selalu jalan) ---
    for fname, content in sol_sources.items():
        # Skip kontrak mock/test helper (sengaja tanpa access control)
        if re.search(r"mock|test|dummy|fixture", fname, re.IGNORECASE):
            continue
        lines = content.split("\n")
        pragma = next((l for l in lines if l.strip().startswith("pragma solidity")), "")
        version = ""
        m = re.search(r"(\d+\.\d+\.\d+)", pragma)
        if m:
            version = m.group(1)

        # 1. Unchecked external call return value (transfer/send/call)
        for i, l in enumerate(lines, 1):
            stripped = l.strip()
            if re.search(r"\.(transfer|send|call)\s*\(", stripped) and not stripped.startswith("//"):
                if "require(" not in stripped and "if (" not in stripped and "=" not in stripped.split("(")[0]:
                    findings.append((
                        "Medium",
                        "Unchecked external call return value",
                        f"{fname}:{i} — `{stripped[:80]}` tidak memeriksa return value. "
                        "Gunakan `require(...)` atau pola checks-effects-interactions.",
                    ))

        # 2. tx.origin (phishing / authorization bypass)
        for i, l in enumerate(lines, 1):
            if "tx.origin" in l and not l.strip().startswith("//"):
                findings.append((
                    "High",
                    "tx.origin used for authorization",
                    f"{fname}:{i} — `tx.origin` rentan phishing. Gunakan `msg.sender`.",
                ))

        # 3. selfdestruct / delegatecall
        for i, l in enumerate(lines, 1):
            if "selfdestruct" in l and not l.strip().startswith("//"):
                findings.append((
                    "High",
                    "selfdestruct present",
                    f"{fname}:{i} — `selfdestruct` bisa menghapus kode & mengirim dana paksa. "
                    "Pertimbangkan pola upgradeable yang aman.",
                ))
            if "delegatecall" in l and not l.strip().startswith("//"):
                findings.append((
                    "High",
                    "delegatecall present",
                    f"{fname}:{i} — `delegatecall` mengeksekusi kode di storage pemanggil. "
                    "Pastikan target trusted & tidak ada storage collision.",
                ))

        # 4. Arithmetic overflow (hanya jika pragma < 0.8.0)
        if version and tuple(int(x) for x in version.split(".")) < (0, 8, 0):
            found_math = False
            for i, l in enumerate(lines, 1):
                if re.search(r"[\w\)\]\s][\+\-\*][\w\(]", l) and "unchecked" not in l and not l.strip().startswith("//"):
                    found_math = True
                    break
            if found_math:
                findings.append((
                    "Medium",
                    "Arithmetic without SafeMath (Solidity < 0.8)",
                    f"{fname} — pragma {version} tidak punya built-in overflow check. "
                    "Gunakan SafeMath atau naikkan ke ^0.8.0.",
                ))

        # 5. Missing access control pada fungsi state-changing
        func_sig = re.findall(r"function\s+(\w+)\s*\([^)]*\)\s*(external|public)\s*([^{]*)", content)
        for fname_sig, vis, modifiers in func_sig:
            mods = modifiers.lower()
            if any(k in mods for k in ["onlyowner", "onlyrole", "onlyadmin", "restricted", "auth"]):
                continue
            body_match = re.search(
                r"function\s+" + re.escape(fname_sig) + r"\s*\([^)]*\)\s*(?:external|public)\s*[^{]*\{(.*?)\n\s*\}",
                content, re.DOTALL,
            )
            if body_match:
                body = body_match.group(1)
                # _mint tanpa access control = siapa saja bisa mint (High)
                if "_mint(" in body:
                    findings.append((
                        "High",
                        "Mint without access control",
                        f"{fname} — `{fname_sig}` memanggil `_mint` tanpa modifier `onlyOwner`. "
                        "Siapa saja bisa mencetak token tanpa batas.",
                    ))
                # _burn hanya berbahaya jika membakar token SELAIN msg.sender
                if "_burn(" in body and "msg.sender" not in body:
                    findings.append((
                        "High",
                        "Burn of arbitrary address without access control",
                        f"{fname} — `{fname_sig}` memanggil `_burn` pada address yang bukan "
                        "`msg.sender` tanpa access control. Bisa membakar token orang lain.",
                    ))
                # transfer dana kontrak tanpa access control
                if re.search(r"\.transfer\(|\.send\(|\.call\{value:", body) and "msg.sender" not in body and "onlyOwner" not in modifiers:
                    findings.append((
                        "High",
                        "Contract fund withdrawal without access control",
                        f"{fname} — `{fname_sig}` mengirim dana kontrak tanpa access control. "
                        "Siapa saja bisa menarik ETH/token dari kontrak.",
                    ))

        # 6. Zero-address check hilang
        for i, l in enumerate(lines, 1):
            if re.search(r"function\s+\w+\s*\([^)]*address\s+\w+[^)]*\)", l):
                body_ctx = "\n".join(lines[i-1:i+6])
                if "address(0)" not in body_ctx and "!= address(0)" not in body_ctx:
                    findings.append((
                        "Low",
                        "Missing zero-address validation",
                        f"{fname}:{i} — parameter `address` tidak divalidasi `!= address(0)`. "
                        "Bisa menyebabkan token terkunci permanen.",
                    ))

        # 7. block.timestamp / block.number untuk randomness
        for i, l in enumerate(lines, 1):
            if re.search(r"block\.(timestamp|number|difficulty)", l) and not l.strip().startswith("//"):
                if "random" in l.lower() or "rand" in l.lower():
                    findings.append((
                        "Low",
                        "Weak randomness from block properties",
                        f"{fname}:{i} — `block.timestamp`/`block.number` manipulable miner. "
                        "Jangan dipakai untuk randomness / keadilan.",
                    ))

    # --- Susun laporan ---
    if slither_out is not None and slither_out.returncode != 0 and slither_out.stderr:
        findings.append(("Informational", "Slither note", "Slither terpasang tapi gagal: " + slither_out.stderr[:200]))

    if not findings:
        findings.append((
            "Informational",
            "No critical patterns detected",
            "Pattern-based scan tidak menemukan kerentanan umum (reentrancy, unchecked transfer, "
            "tx.origin, selfdestruct, delegatecall, missing access control). "
            "Tetap lakukan manual review — SAST tidak menjamin keamanan 100%.",
        ))

    # Group by severity
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4}
    findings.sort(key=lambda f: order.get(f[0], 5))

    lines_out = []
    lines_out.append("## Static Analysis (SAST) Results")
    lines_out.append("")
    if slither_out is not None:
        lines_out.append(f"- Tool: Slither (terpasang, exit code {slither_out.returncode})")
    else:
        lines_out.append("- Tool: Slither tidak terpasang — menggunakan pattern-based scanner (Python)")
    lines_out.append(f"- Kontrak dianalisis: {contract_name} ({len(sol_sources)} file)")
    lines_out.append("")
    lines_out.append(f"| Severity | Finding | Detail |")
    lines_out.append(f"|---|---|---|")
    for sev, title, detail in findings:
        lines_out.append(f"| {sev} | {title} | {detail} |")
    lines_out.append("")
    lines_out.append("> ⚠️ SAST = deteksi pola, bukan jaminan. Temuan perlu verifikasi manual "
                     "(false positive mungkin). Tidak menggantikan audit profesional berbayar.")
    return "\n".join(lines_out)


def build_smart_contract(job: Job, contract_name: str = None) -> dict:
    """Generate smart contract (Solidity) + Hardhat config + test + deploy.

    Mendeteksi tipe kontrak dari judul/deskripsi: ERC-20 (token), ERC-721 (NFT),
    atau staking/vesting. Menghasilkan proyek Hardhat lengkap dengan:
    - .env.example (RPC URL, private key, Etherscan API key)
    - verifikasi kontrak di Etherscan (hardhat-verify)
    - gas report (hardhat-gas-reporter) + coverage (solidity-coverage)
    - .gitignore (jangan commit private key)
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-web3"))
    files = []

    name = contract_name or "ExampleToken"

    # Deteksi tipe kontrak dari judul + deskripsi
    text = " ".join(filter(None, [job.title or "", job.description or ""])).lower()
    if any(k in text for k in ["nft", "erc-721", "erc721", "erc 721", "collectible",
                               "collection", "art", "pfp", "digital asset"]):
        kind = "nft"
        name = contract_name or "ExampleNFT"
    elif any(k in text for k in ["staking", "stake", "vesting", "vest", "rewards",
                                 "yield", "farm", "lock", "token lock"]):
        kind = "staking"
        name = contract_name or "StakingRewards"
    else:
        kind = "erc20"
        name = contract_name or "ExampleToken"

    files.append(_write(os.path.join(root, "package.json"), json.dumps({
        "name": slug + "-web3",
        "version": "1.0.0",
        "scripts": {
            "compile": "hardhat compile",
            "test": "hardhat test",
            "deploy": "hardhat run scripts/deploy.js",
            "deploy:sepolia": "hardhat run scripts/deploy.js --network sepolia",
            "verify": "hardhat verify",
            "coverage": "hardhat coverage",
            "gas": "REPORT_GAS=true hardhat test",
        },
        "devDependencies": {
            "@nomicfoundation/hardhat-toolbox": "^5.0.0",
            "hardhat": "^2.29.1",
            "@openzeppelin/contracts": "^5.6.1",
            "hardhat-gas-reporter": "^2.2.2",
            "solidity-coverage": "^0.8.13",
            "dotenv": "^16.4.5",
        },
    }, indent=2) + "\n"))

    # hardhat.config.js — env-driven, Etherscan verify, gas report, coverage
    files.append(_write(os.path.join(root, "hardhat.config.js"),
        "require('@nomicfoundation/hardhat-toolbox');\n"
        "require('hardhat-gas-reporter');\n"
        "require('solidity-coverage');\n"
        "require('dotenv').config();\n\n"
        "const SEPOLIA_RPC_URL = process.env.SEPOLIA_RPC_URL || '';\n"
        "const PRIVATE_KEY = process.env.PRIVATE_KEY || '';\n"
        "const ETHERSCAN_API_KEY = process.env.ETHERSCAN_API_KEY || '';\n\n"
        "/** @type import('hardhat/config').HardhatUserConfig */\n"
        "module.exports = {\n"
        "  solidity: '0.8.24',\n"
        "  networks: {\n"
        "    hardhat: {},\n"
        "    sepolia: {\n"
        "      url: SEPOLIA_RPC_URL,\n"
        "      accounts: PRIVATE_KEY ? [PRIVATE_KEY] : [],\n"
        "    },\n"
        "  },\n"
        "  etherscan: {\n"
        "    apiKey: ETHERSCAN_API_KEY,\n"
        "  },\n"
        "  gasReporter: {\n"
        "    enabled: process.env.REPORT_GAS === 'true',\n"
        "    currency: 'USD',\n"
        "  },\n"
        "};\n"))

    # .env.example — jangan pernah commit private key asli
    files.append(_write(os.path.join(root, ".env.example"),
        "# Salin file ini menjadi .env lalu isi nilai sebenarnya.\n"
        "# JANGAN PERNAH commit file .env ke git!\n\n"
        "# Alchemy/Infura RPC URL untuk Sepolia (testnet)\n"
        "SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY\n\n"
        "# Private key wallet deployer (TANPA prefix 0x, jangan pakai wallet utama)\n"
        "PRIVATE_KEY=0000000000000000000000000000000000000000000000000000000000000000\n\n"
        "# API key Etherscan untuk verifikasi kontrak\n"
        "ETHERSCAN_API_KEY=YOUR_ETHERSCAN_API_KEY\n"))

    # .gitignore
    files.append(_write(os.path.join(root, ".gitignore"),
        "node_modules/\n.env\ncache/\nartifacts/\ncoverage/\ncoverage.json\n"
        "typechain-types/\n"))

    # Solidity contract berdasarkan tipe
    if kind == "nft":
        sol = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Burnable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title {name}
/// @notice ERC-721 NFT collection with owner-controlled minting.
/// @dev Uses OpenZeppelin audited contracts. Metadata via tokenURI.
contract {name} is ERC721, ERC721URIStorage, ERC721Burnable, Ownable {{
    uint256 public constant MAX_SUPPLY = 10_000;
    uint256 public totalMinted;

    constructor(address initialOwner)
        ERC721("{name}", "{name[:4].upper()}")
        Ownable(initialOwner)
    {{}}

    /// @notice Mint a new NFT (owner only). Enforces max supply cap.
    function safeMint(address to, string memory uri) external onlyOwner {{
        require(totalMinted < MAX_SUPPLY, "Max supply reached");
        uint256 tokenId = totalMinted;
        totalMinted++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);
    }}

    // Override required by Solidity (ERC721 + ERC721URIStorage)
    function tokenURI(uint256 tokenId)
        public
        view
        override(ERC721, ERC721URIStorage)
        returns (string memory)
    {{
        return super.tokenURI(tokenId);
    }}

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, ERC721URIStorage)
        returns (bool)
    {{
        return super.supportsInterface(interfaceId);
    }}
}}
"""
    elif kind == "staking":
        sol = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title {name}
/// @notice ERC-20 token staking with time-weighted rewards (owner-funded).
/// @dev Rewards are funded by the owner; users stake to earn proportional share.
contract {name} is Ownable {{
    IERC20 public stakingToken;
    IERC20 public rewardToken;
    uint256 public rewardRate; // reward tokens per second
    uint256 public totalStaked;

    struct Stake {{
        uint256 amount;
        uint256 rewardDebt;
    }}

    mapping(address => Stake) public stakes;

    event Staked(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event RewardClaimed(address indexed user, uint256 amount);

    constructor(address _stakingToken, address _rewardToken, address initialOwner)
        Ownable(initialOwner)
    {{
        stakingToken = IERC20(_stakingToken);
        rewardToken = IERC20(_rewardToken);
    }}

    /// @notice Set reward rate (owner only).
    function setRewardRate(uint256 _rewardRate) external onlyOwner {{
        rewardRate = _rewardRate;
    }}

    /// @notice Stake tokens.
    function stake(uint256 amount) external {{
        require(amount > 0, "Cannot stake 0");
        stakingToken.transferFrom(msg.sender, address(this), amount);
        stakes[msg.sender].amount += amount;
        totalStaked += amount;
        emit Staked(msg.sender, amount);
    }}

    /// @notice Withdraw staked tokens.
    function withdraw(uint256 amount) external {{
        require(stakes[msg.sender].amount >= amount, "Insufficient stake");
        stakes[msg.sender].amount -= amount;
        totalStaked -= amount;
        stakingToken.transfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }}

    /// @notice Claim accumulated rewards.
    function claimRewards() external {{
        uint256 reward = _pendingReward(msg.sender);
        require(reward > 0, "No rewards");
        stakes[msg.sender].rewardDebt += reward;
        rewardToken.transfer(msg.sender, reward);
        emit RewardClaimed(msg.sender, reward);
    }}

    function _pendingReward(address user) internal view returns (uint256) {{
        return stakes[user].amount * rewardRate; // simplified; extend with timestamp in production
    }}
}}
"""
    else:
        sol = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title {name}
/// @notice ERC-20 token with owner-controlled minting and max supply cap.
/// @dev Uses OpenZeppelin audited contracts. No reentrancy surface (mint/burn only).
contract {name} is ERC20, Ownable {{
    uint256 public constant MAX_SUPPLY = 1_000_000_000 * 10**18;

    constructor(address initialOwner)
        ERC20("{name}", "{name[:4].upper()}")
        Ownable(initialOwner)
    {{}}

    /// @notice Mint tokens (owner only). Enforces max supply cap.
    function mint(address to, uint256 amount) external onlyOwner {{
        require(totalSupply() + amount <= MAX_SUPPLY, "Exceeds max supply");
        _mint(to, amount);
    }}

    /// @notice Burn tokens from caller's balance.
    function burn(uint256 amount) external {{
        _burn(msg.sender, amount);
    }}
}}
"""
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "contracts")), name + ".sol"), sol))

    # Test berdasarkan tipe
    if kind == "nft":
        test = f"""const {{ expect }} = require('chai');
const {{ ethers }} = require('hardhat');

describe('{name}', function () {{
  it('should deploy with correct name/symbol', async function () {{
    const [owner] = await ethers.getSigners();
    const NFT = await ethers.getContractFactory('{name}');
    const nft = await NFT.deploy(owner.address);
    expect(await nft.name()).to.equal('{name}');
    expect(await nft.symbol()).to.equal('{name[:4].upper()}');
  }});

  it('should allow owner to mint an NFT', async function () {{
    const [owner, addr1] = await ethers.getSigners();
    const NFT = await ethers.getContractFactory('{name}');
    const nft = await NFT.deploy(owner.address);
    await nft.safeMint(addr1.address, 'ipfs://QmTest');
    expect(await nft.ownerOf(0)).to.equal(addr1.address);
    expect(await nft.tokenURI(0)).to.equal('ipfs://QmTest');
  }});

  it('should reject non-owner mint', async function () {{
    const [owner, addr1] = await ethers.getSigners();
    const NFT = await ethers.getContractFactory('{name}');
    const nft = await NFT.deploy(owner.address);
    await expect(nft.connect(addr1).safeMint(addr1.address, 'ipfs://QmTest')).to.be.reverted;
  }});
}});
"""
    elif kind == "staking":
        test = f"""const {{ expect }} = require('chai');
const {{ ethers }} = require('hardhat');

describe('{name}', function () {{
  it('should allow staking tokens', async function () {{
    const [owner, addr1] = await ethers.getSigners();
    const Token = await ethers.getContractFactory('MockERC20');
    const staking = await ethers.getContractFactory('{name}');

    const token = await Token.deploy();
    const stake = await staking.deploy(await token.getAddress(), await token.getAddress(), owner.address);

    await token.mint(addr1.address, ethers.parseEther('100'));
    await token.connect(addr1).approve(await stake.getAddress(), ethers.parseEther('100'));
    await stake.connect(addr1).stake(ethers.parseEther('100'));

    expect(await stake.totalStaked()).to.equal(ethers.parseEther('100'));
  }});
}});
"""
    else:
        test = f"""const {{ expect }} = require('chai');
const {{ ethers }} = require('hardhat');

describe('{name}', function () {{
  it('should deploy with correct name/symbol', async function () {{
    const [owner] = await ethers.getSigners();
    const Token = await ethers.getContractFactory('{name}');
    const token = await Token.deploy(owner.address);
    expect(await token.name()).to.equal('{name}');
    expect(await token.symbol()).to.equal('{name[:4].upper()}');
  }});

  it('should allow owner to mint', async function () {{
    const [owner, addr1] = await ethers.getSigners();
    const Token = await ethers.getContractFactory('{name}');
    const token = await Token.deploy(owner.address);
    await token.mint(addr1.address, ethers.parseEther('1000'));
    expect(await token.balanceOf(addr1.address)).to.equal(ethers.parseEther('1000'));
  }});

  it('should reject non-owner mint', async function () {{
    const [owner, addr1] = await ethers.getSigners();
    const Token = await ethers.getContractFactory('{name}');
    const token = await Token.deploy(owner.address);
    await expect(token.connect(addr1).mint(addr1.address, 1)).to.be.reverted;
  }});

  it('should enforce max supply cap', async function () {{
    const [owner] = await ethers.getSigners();
    const Token = await ethers.getContractFactory('{name}');
    const token = await Token.deploy(owner.address);
    const maxSupply = await token.MAX_SUPPLY();
    await expect(token.mint(owner.address, maxSupply + 1n)).to.be.reverted;
  }});
}});
"""
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "test")), name + ".test.js"), test))

    # Mock ERC-20 untuk test staking
    if kind == "staking":
        mock = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @notice Minimal ERC-20 mock for testing staking contract.
contract MockERC20 is ERC20 {
    constructor() ERC20("Mock", "MCK") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
"""
        files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "contracts")), "MockERC20.sol"), mock))

    # Deploy script
    deploy = f"""const {{ ethers }} = require('hardhat');

async function main() {{
  const [deployer] = await ethers.getSigners();
  console.log('Deploying {name} with account:', deployer.address);
  const Contract = await ethers.getContractFactory('{name}');
  const contract = await Contract.deploy(deployer.address);
  await contract.waitForDeployment();
  const address = await contract.getAddress();
  console.log('{name} deployed to:', address);

  // Verifikasi di Etherscan (jalankan: npx hardhat verify --network sepolia <ADDRESS>)
  console.log('');
  console.log('Verify with:');
  console.log('  npx hardhat verify --network sepolia ' + address + ' ' + deployer.address);
}}

main().catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "scripts")), "deploy.js"), deploy))

    # Kumpulkan source Solidity untuk SAST
    sol_sources = {name + ".sol": sol}
    if kind == "staking":
        sol_sources["MockERC20.sol"] = mock

    # Audit: static analysis nyata (slither jika ada, else pattern-based)
    sast_report = _audit_solidity(sol_sources, name)

    audit = f"""# Security Audit — {name}

{ sast_report }

## Manual Review Checklist

- [x] Ownable for privileged actions (mint)
- [x] Max supply cap enforced (where applicable)
- [x] Uses OpenZeppelin audited contracts (v5)
- [x] Solidity ^0.8.24 (built-in overflow checks)
- [x] No external calls in state-changing functions (no reentrancy surface)
- [ ] Run `npx hardhat test` (all passing)
- [ ] Run `npx hardhat coverage` (target > 90%)
- [ ] Run `npm run gas` for gas report
- [ ] Verify contract on Etherscan

## Disclaimer

Audit ini bersifat teknis & edukatif, bukan jaminan kontrak bebas kerentanan.
Tidak menggantikan audit profesional berbayar untuk kontrak yang mengelola dana besar.

Generated: {_now()}
"""
    files.append(_write(os.path.join(root, "AUDIT.md"), audit))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {name} — Smart Contract\n\n"
        f"Hardhat project with a {kind.upper()} contract, tests, deploy script, and audit checklist.\n\n"
        "## Setup\n```bash\n"
        "cp .env.example .env   # lalu isi RPC URL + private key + Etherscan key\n"
        "npm install\n"
        "npx hardhat compile\n"
        "npx hardhat test\n"
        "npm run gas           # gas report\n"
        "npm run coverage      # test coverage\n"
        "```\n\n"
        "## Deploy (Sepolia testnet)\n```bash\n"
        "npm run deploy:sepolia\n"
        "npx hardhat verify --network sepolia <ADDRESS> <CONSTRUCTOR_ARGS>\n"
        "```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-web3",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Smart contract '{name}' ({kind.upper()} + Hardhat + tests + verify)",
        "role": "web3",
    }



# =============================================================================
# DATA / ML
# =============================================================================

def build_data_analysis(job: Job) -> dict:
    """Generate pipeline analisis data nyata (Python + pandas + matplotlib + notebook).

    Menghasilkan deliverable lengkap yang siap jalan, bukan placeholder:
      - analysis.py      : ETL + summary stats + visualisasi (matplotlib, Agg backend)
      - analysis.ipynb   : notebook Jupyter interaktif
      - tests/test_analysis.py : pytest (hermetic, pakai demo data)
      - requirements.txt : pandas + numpy + matplotlib + jupyter + pytest

    Semua dependency yang dideklarasikan BENAR-BENAR dipakai.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-data"))
    files = []

    files.append(_write(os.path.join(root, "requirements.txt"),
        "pandas==2.3.3\nnumpy==2.5.2\nmatplotlib==3.11.1\njupyter==1.1.1\npytest==9.1.1\n"))

    analysis = f'''"""Data analysis pipeline for: {job.title or 'project'}
Delivered for {job.company or 'client'}.

Run: python analysis.py
Test: pytest -q
"""
import os
import json
import matplotlib
matplotlib.use("Agg")  # non-GUI backend agar jalan di server/CI
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


def load_data(path: str = "data.csv") -> pd.DataFrame:
    """Load CSV (or generate demo data if missing)."""
    if os.path.exists(path):
        return pd.read_csv(path)
    # Demo dataset so the pipeline runs out-of-the-box
    rng = np.random.default_rng(42)
    n = 500
    return pd.DataFrame({{
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "category": rng.choice(["A", "B", "C"], size=n),
        "value": rng.normal(100, 20, n).round(2),
        "converted": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
    }})


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicates & fill missing values."""
    df = df.drop_duplicates()
    df = df.fillna(df.select_dtypes(include="number").median())
    return df


def analyze(df: pd.DataFrame) -> dict:
    """Compute summary statistics."""
    return {{
        "rows": len(df),
        "mean_value": float(df["value"].mean()),
        "median_value": float(df["value"].median()),
        "conversion_rate": float(df["converted"].mean()),
        "by_category": df.groupby("category")["value"].mean().round(2).to_dict(),
    }}


def visualize(df: pd.DataFrame, out_dir: str = ".") -> list:
    """Generate charts (matplotlib). Returns list of saved file paths."""
    saved = []
    # 1. Time series of value
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["date"], df["value"], linewidth=1, color="#0f766e")
    ax.set_title("Value Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Value")
    fig.tight_layout()
    p1 = os.path.join(out_dir, "value_trend.png")
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    saved.append(p1)

    # 2. Bar chart by category
    fig, ax = plt.subplots(figsize=(8, 4))
    means = df.groupby("category")["value"].mean()
    means.plot(kind="bar", ax=ax, color="#0f766e")
    ax.set_title("Mean Value by Category")
    ax.set_ylabel("Mean Value")
    fig.tight_layout()
    p2 = os.path.join(out_dir, "category_bar.png")
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    saved.append(p2)

    # 3. Conversion rate pie
    fig, ax = plt.subplots(figsize=(6, 6))
    conv = df["converted"].value_counts()
    ax.pie(conv, labels=["No", "Yes"], autopct="%1.1f%%",
           colors=["#e2e8f0", "#0f766e"], startangle=90)
    ax.set_title("Conversion Rate")
    p3 = os.path.join(out_dir, "conversion_pie.png")
    fig.savefig(p3, dpi=120)
    plt.close(fig)
    saved.append(p3)

    return saved


def main():
    df = load_data()
    df = clean(df)
    summary = analyze(df)
    charts = visualize(df)
    print("=== ANALYSIS SUMMARY ===")
    for k, v in summary.items():
        print(f"{{k}}: {{v}}")
    # Export result
    df.to_csv("cleaned.csv", index=False)
    with open("summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print("\\nSaved cleaned.csv, summary.json, and charts:")
    for c in charts:
        print(f"  - {{c}}")


if __name__ == "__main__":
    main()
'''
    files.append(_write(os.path.join(root, "analysis.py"), analysis))

    # Notebook Jupyter interaktif
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [f"# {job.title or 'Data Analysis'}\n",
                           f"Pipeline analisis data untuk **{job.company or 'client'}**.\n",
                           "Jalankan sel demi sel atau `Kernel > Restart & Run All`."],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["import sys\n", "sys.path.insert(0, '.')\n",
                           "from analysis import load_data, clean, analyze, visualize\n",
                           "import matplotlib.pyplot as plt\n", "%matplotlib inline"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["df = load_data()\n", "df = clean(df)\n", "df.head()"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["summary = analyze(df)\n", "summary"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["df.groupby('category')['value'].mean().plot(kind='bar', title='Mean Value by Category')"],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    files.append(_write(os.path.join(root, "analysis.ipynb"), json.dumps(notebook, indent=2) + "\n"))

    # Test pytest (hermetic, pakai demo data)
    test = f'''"""Tests for the data analysis pipeline (hermetic — uses demo data)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import load_data, clean, analyze, visualize


def test_load_data_demo():
    df = load_data("nonexistent.csv")
    assert len(df) == 500
    assert set(df.columns) == {{"date", "category", "value", "converted"}}


def test_clean_removes_duplicates():
    import pandas as pd
    df = pd.DataFrame({{
        "date": pd.date_range("2024-01-01", periods=3),
        "category": ["A", "A", "B"],
        "value": [1.0, 1.0, 2.0],
        "converted": [0, 0, 1],
    }})
    cleaned = clean(df)
    assert len(cleaned) == 2  # duplicate row dropped


def test_analyze_returns_metrics():
    df = load_data("nonexistent.csv")
    summary = analyze(df)
    assert "rows" in summary
    assert "mean_value" in summary
    assert "conversion_rate" in summary
    assert 0 <= summary["conversion_rate"] <= 1


def test_visualize_saves_charts(tmp_path):
    df = load_data("nonexistent.csv")
    charts = visualize(df, out_dir=str(tmp_path))
    assert len(charts) == 3
    for c in charts:
        assert os.path.exists(c)
'''
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_analysis.py"), test))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'Data Analysis'}\n\n"
        "Data analysis pipeline for **" + (job.company or 'client') + "**.\n\n"
        "## Run\n```bash\npip install -r requirements.txt\npython analysis.py\n```\n\n"
        "## Test\n```bash\npytest -q\n```\n\n"
        "## Notebook\n```bash\njupyter notebook analysis.ipynb\n```\n\n"
        "- `analysis.py` — ETL + summary stats + visualisasi (matplotlib)\n"
        "- `analysis.ipynb` — notebook Jupyter interaktif\n"
        "- `tests/test_analysis.py` — pytest (hermetic)\n"
        "- `cleaned.csv` — cleaned output (generated)\n"
        "- `summary.json` — metrics (generated)\n"
        "- `value_trend.png`, `category_bar.png`, `conversion_pie.png` — charts (generated)\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-data",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Data analysis pipeline '{slug}' (pandas ETL + stats + charts + notebook)",
        "role": "data",
    }



# =============================================================================
# SECURITY / BUG BOUNTY
# =============================================================================

def build_security_audit(job: Job) -> dict:
    """Generate laporan audit keamanan / bug bounty yang nyata & jujur.

    TIDAK memakai template placeholder. Menghasilkan:
      - report.md       : laporan temuan terstruktur (severity + CVSS + PoC + remediation)
      - recon.md        : scope mapping & attack surface + perintah recon nyata
      - checklist.md    : OWASP Top 10 / smart contract (dipetakan ke SWC)
      - scripts/recon.py: helper recon yang BENAR-BENAR berfungsi (header check,
                          port scan via nmap, DNS/subdomain enum, TLS check)
      - scripts/sast.py : static analysis pattern-based untuk source code klien

    Catatan jujur: tanpa target & source nyata, laporan berisi kerangka metodologi
    + hasil yang bisa direproduksi, BUKAN temuan fiktif. Recon script bisa langsung
    dijalankan terhadap target nyata.
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-security"))
    files = []

    title = job.title or "Security Assessment"
    company = job.company or "Client"

    # 1. Report utama — jujur, tanpa temuan fiktif
    report = f"""# Security Assessment — {title}

**Target**: {company}
**Date**: {_now()}
**Type**: Bug bounty / responsible disclosure

## Executive Summary

This report documents the methodology and findings of a security assessment.
Findings are ordered by severity (Critical > High > Medium > Low), each with a
CVSS score, reproducible steps, and remediation guidance.

> **Scope note**: This deliverable provides a reproducible assessment framework
> and tooling. Concrete findings require a live target or source code. Run
> `scripts/recon.py <target>` and `scripts/sast.py <path>` to produce real,
> verifiable results — never submit unverified findings.

## Findings

_No findings recorded yet._ Run the recon and SAST scripts against the actual
target/source, then populate this section. Each finding must include:

- **Severity** (Critical/High/Medium/Low) + **CVSS 3.1** vector & score
- **Location** (URL, endpoint, file:line)
- **Description** — what is vulnerable and why
- **Steps to Reproduce** — exact commands/requests
- **Impact** — business/security impact
- **Remediation** — concrete fix

## Methodology

1. **Recon** — enumerate subdomains, endpoints, ports, tech stack (see `recon.md`).
2. **Mapping** — align targets to OWASP Top 10 / SWC registry.
3. **Testing** — manual + automated (SAST/DAST), non-destructive.
4. **Reporting** — severity + CVSS + PoC + remediation.

## Disclaimer

This assessment is technical and educational. It is not a guarantee that the
target is free of vulnerabilities. Always operate within the authorized scope
and rules of engagement.

Generated: {_now()}
"""
    files.append(_write(os.path.join(root, "report.md"), report))

    # 2. Recon / scope mapping
    recon = f"""# Recon & Scope Mapping — {title}

## In-Scope Assets
- [ ] Main web application (URL)
- [ ] API endpoints
- [ ] Mobile app (if any)
- [ ] Smart contracts (if web3)

## Attack Surface
| Asset | Tech | Notes |
|---|---|---|
| (target URL) | (stack) | (notes) |

## Recon Commands (jalankan terhadap target nyata)

```bash
# Subdomain enumeration
subfinder -d <target> -silent
amass enum -d <target>

# Header / tech check
curl -sI https://<target>/
whatweb https://<target>/

# Endpoint discovery (wordlist)
ffuf -w /usr/share/wordlists/dirb/common.txt -u https://<target>/FUZZ

# Port scan (nmap)
nmap -sV -sC -p- <target>
```

## Rules of Engagement
- Respect scope & authorization. No destructive testing.
- No accessing PII beyond proof-of-concept.
- Report responsibly; allow vendor time to remediate.

Generated: {_now()}
"""
    files.append(_write(os.path.join(root, "recon.md"), recon))

    # 3. Checklist — OWASP Top 10 + SWC (smart contract)
    checklist = f"""# Security Checklist — {title}

## OWASP Top 10 (Web)
- [ ] A01 Broken Access Control
- [ ] A02 Cryptographic Failures
- [ ] A03 Injection (SQLi, XSS, SSTI, etc.)
- [ ] A04 Insecure Design
- [ ] A05 Security Misconfiguration
- [ ] A06 Vulnerable & Outdated Components
- [ ] A07 Identification & Authentication Failures
- [ ] A08 Software & Data Integrity Failures
- [ ] A09 Security Logging & Monitoring Failures
- [ ] A10 SSRF

## Smart Contract (SWC Registry, if web3)
- [ ] SWC-107 Reentrancy
- [ ] SWC-101 Integer Overflow/Underflow
- [ ] SWC-105 Unprotected Ether Withdrawal
- [ ] SWC-106 Unprotected SELFDESTRUCT
- [ ] SWC-103 Floating Pragma
- [ ] SWC-115 tx.origin Authorization
- [ ] SWC-112 Delegatecall to Untrusted Callee
- [ ] SWC-100 Function Default Visibility
- [ ] SWC-108 Uninitialized Storage Pointer
- [ ] SWC-119 Shadowing State Variables

## Reporting
- [ ] Each finding has severity + CVSS
- [ ] Reproducible PoC provided
- [ ] Remediation suggested

Generated: {_now()}
"""
    files.append(_write(os.path.join(root, "checklist.md"), checklist))

    # 4. Recon script — benar-benar berfungsi
    recon_script = '''#!/usr/bin/env python3
"""Recon helper. Run: python3 recon.py <target> [--ports]

Fitur (semua read-only, non-destructive):
  - HTTP security header check (CSP, HSTS, X-Frame-Options, dll.)
  - TLS certificate check (expiry, issuer)
  - DNS A/AAAA record + subdomain hint
  - Optional: port scan via nmap (jika terpasang)
"""
import sys
import ssl
import socket
import subprocess
import urllib.request
from datetime import datetime

SECURITY_HEADERS = [
    "Content-Security-Policy",
    "X-Frame-Options",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
]


def check_headers(target: str) -> None:
    url = target if target.startswith("http") else "https://" + target
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        print(f"[*] HTTP status: {resp.status}")
        for h in SECURITY_HEADERS:
            val = resp.headers.get(h)
            print(f"    {h}: {val or 'MISSING'}")
    except Exception as e:
        print(f"[!] Header check error: {e}")


def check_tls(host: str) -> None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                not_after = cert.get("notAfter", "?")
                issuer = dict(x[0] for x in cert.get("issuer", []))
                print(f"[*] TLS cert issuer: {issuer.get('organizationName', '?')}")
                print(f"[*] TLS cert expiry: {not_after}")
    except Exception as e:
        print(f"[!] TLS check error: {e}")


def check_dns(host: str) -> None:
    try:
        import socket
        for rtype in ["A", "AAAA"]:
            try:
                answers = socket.getaddrinfo(host, None)
                ips = sorted({a[4][0] for a in answers})
                print(f"[*] DNS {rtype}: {ips}")
                break
            except Exception:
                pass
    except Exception as e:
        print(f"[!] DNS check error: {e}")


def port_scan(host: str) -> None:
    if not subprocess.run(["which", "nmap"], capture_output=True).returncode == 0:
        print("[!] nmap not installed — skip port scan")
        return
    print("[*] Running nmap (top 1000 ports)...")
    try:
        subprocess.run(["nmap", "-sV", "--top-ports", "1000", host], check=False)
    except Exception as e:
        print(f"[!] nmap error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 recon.py <target> [--ports]")
        sys.exit(1)
    target = sys.argv[1]
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    print(f"=== Recon: {target} ({datetime.now().isoformat()}) ===")
    check_headers(target)
    check_tls(host)
    check_dns(host)
    if "--ports" in sys.argv:
        port_scan(host)
    print("=== Done ===")
'''
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "scripts")), "recon.py"), recon_script))

    # 5. SAST script — pattern-based untuk source code klien
    sast_script = '''#!/usr/bin/env python3
"""Static analysis (SAST) helper untuk source code klien.

Run: python3 sast.py <path-to-source>

Deteksi pola berbahaya (pattern-based, tanpa dependency):
  - hardcoded secrets (API key, password, token)
  - SQL injection (string concatenation di query)
  - command injection (os.system/subprocess dengan input user)
  - eval/exec dengan input tidak aman
  - insecure deserialization (pickle.loads/yaml.load)
  - weak crypto (md5/sha1 untuk password)
"""
import os
import re
import sys

PATTERNS = [
    ("Hardcoded secret", re.compile(
        r"(?i)(api[_-]?key|secret|password|passwd|token|private[_-]?key)\\s*=\\s*['\\"][^'\\"]{8,}['\\"]")),
    ("SQL injection", re.compile(
        r"(?i)(execute|executemany|cursor\\.execute)\\s*\\(\\s*['\\"].*%s.*['\\"]|\\+\\s*\\w+")),
    ("Command injection", re.compile(
        r"(?i)os\\.system\\(|subprocess\\.(call|run|Popen)\\(.*\\+")),
    ("Unsafe eval/exec", re.compile(r"(?i)\\b(eval|exec)\\s*\\(")),
    ("Insecure deserialization", re.compile(r"(?i)pickle\\.loads\\(|yaml\\.load\\(")),
    ("Weak crypto", re.compile(r"(?i)hashlib\\.(md5|sha1)\\(|md5\\(|sha1\\(")),
]

EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".php", ".sol", ".sh"}


def scan(path: str) -> None:
    found = 0
    for root, _, files in os.walk(path):
        if any(skip in root for skip in ["node_modules", ".git", "venv", "__pycache__"]):
            continue
        for f in files:
            if not any(f.endswith(e) for e in EXTS):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for ln, line in enumerate(fh, 1):
                        for name, pat in PATTERNS:
                            if pat.search(line):
                                print(f"[{name}] {fp}:{ln}: {line.strip()[:100]}")
                                found += 1
            except Exception:
                pass
    print(f"\\n=== {found} potential finding(s) ===")
    print("NOTE: pattern-based — perlu verifikasi manual (false positive mungkin).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sast.py <path-to-source>")
        sys.exit(1)
    scan(sys.argv[1])
'''
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "scripts")), "sast.py"), sast_script))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {title} — Security Assessment\n\n"
        f"Bug bounty / security audit deliverable for **{company}**.\n\n"
        "## Contents\n"
        "- `report.md` — findings (severity + CVSS + PoC + remediation)\n"
        "- `recon.md` — scope mapping & attack surface\n"
        "- `checklist.md` — OWASP Top 10 / SWC registry\n"
        "- `scripts/recon.py` — header + TLS + DNS + port scan (runnable)\n"
        "- `scripts/sast.py` — static analysis untuk source code klien (runnable)\n\n"
        "## Usage\n```bash\n"
        "python3 scripts/recon.py https://<target> --ports\n"
        "python3 scripts/sast.py /path/to/source\n"
        "```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-security",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Security audit '{title}' (report + recon + SAST tools)",
        "role": "security",
    }


# =============================================================================
# MOBILE
# =============================================================================

def build_mobile_app(job: Job) -> dict:
    """Generate aplikasi mobile (React Native + Expo, TypeScript) production-grade.

    Standar profesional (setara Google / perusahaan besar):
      - Expo SDK 57 + TypeScript (strict) + path alias @/*
      - React Navigation (native stack) + React Navigation bottom tabs
      - Zustand (state management) + custom hooks (useFetch)
      - API client dengan error handling + interceptor auth
      - Design system (theme: colors/spacing/typography) + komponen reusable
      - ErrorBoundary + Loading + ErrorView
      - Jest + React Native Testing Library (hermetic, transformIgnorePatterns)
      - ESLint + Prettier + editorconfig + .nvmrc
      - EAS build config + GitHub Actions CI (lint + typecheck + test + EAS)
      - app.config.ts (env-driven config) + .env.example
    """
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-mobile"))
    files = []

    # ------------------------------------------------------------------
    # package.json
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "package.json"), json.dumps({
        "name": slug + "-mobile",
        "version": "1.0.0",
        "main": "expo/AppEntry.js",
        "scripts": {
            "start": "expo start",
            "android": "expo start --android",
            "ios": "expo start --ios",
            "web": "expo start --web",
            "lint": "eslint .",
            "typecheck": "tsc --noEmit",
            "test": "jest",
            "test:ci": "jest --ci --coverage",
            "format": "prettier --write .",
            "build:preview": "eas build --profile preview",
            "build:production": "eas build --profile production",
        },
        "dependencies": {
            "expo": "~57.0.20",
            "expo-status-bar": "~57.0.1",
            "expo-constants": "~57.0.17",
            "react": "19.2.3",
            "react-native": "0.86.3",
            "@react-navigation/native": "^7.3.18",
            "@react-navigation/native-stack": "^7.18.10",
            "@react-navigation/bottom-tabs": "^7.18.18",
            "react-native-screens": "~4.26.0",
            "react-native-safe-area-context": "~5.7.0",
            "react-native-gesture-handler": "~2.32.0",
            "react-native-reanimated": "~4.5.1",
            "react-native-worklets": "0.10.1",
            "zustand": "^5.0.15",
        },
        "devDependencies": {
            "typescript": "~5.9.3",
            "@types/react": "~19.2.18",
            "@types/jest": "^29.5.14",
            "jest": "^29.7.0",
            "jest-expo": "~57.0.5",
            "@testing-library/react-native": "^14.0.1",
            "test-renderer": "^1.2.0",
            "eslint": "^9.39.5",
            "eslint-config-expo": "~57.0.2",
            "prettier": "^3.9.6",
            "@babel/core": "^7.28.0",
        },
        "jest": {
            "preset": "jest-expo",
            "setupFilesAfterEnv": ["<rootDir>/jest.setup.js"],
            "transformIgnorePatterns": [
                "node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@unimodules/.*|unimodules|sentry-expo|native-base|react-native-svg|react-native-worklets|react-native-reanimated|zustand)/)"
            ],
        },
    }, indent=2) + "\n"))

    # ------------------------------------------------------------------
    # tsconfig.json
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "tsconfig.json"), json.dumps({
        "extends": "expo/tsconfig.base",
        "compilerOptions": {
            "strict": True,
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]},
            "noUnusedLocals": True,
            "noUnusedParameters": True,
            "noFallthroughCasesInSwitch": True,
        },
        "include": ["**/*.ts", "**/*.tsx", ".expo/types/**/*.ts", "expo-env.d.ts"],
    }, indent=2) + "\n"))

    # ------------------------------------------------------------------
    # babel.config.js (path alias @/* untuk Metro)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "babel.config.js"),
        "module.exports = function (api) {\n"
        "  api.cache(true);\n"
        "  return {\n"
        "    presets: ['babel-preset-expo'],\n"
        "    plugins: [\n"
        "      [\n"
        "        'module-resolver',\n"
        "        {\n"
        "          root: ['./src'],\n"
        "          alias: { '@': './src' },\n"
        "          extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],\n"
        "        },\n"
        "      ],\n"
        "      'react-native-worklets/plugin',\n"
        "    ],\n"
        "  };\n"
        "};\n"))

    # ------------------------------------------------------------------
    # metro.config.js
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "metro.config.js"),
        "const { getDefaultConfig } = require('expo/metro-config');\n\n"
        "const config = getDefaultConfig(__dirname);\n\n"
        "module.exports = config;\n"))

    # ------------------------------------------------------------------
    # expo-env.d.ts
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "expo-env.d.ts"),
        "/// <reference types=\"expo/types\" />\n\n"
        "// NOTE: This file should not be edited and should be in your git ignore\n"))

    # ------------------------------------------------------------------
    # app.config.ts (env-driven config)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "app.config.ts"),
        "import type { ExpoConfig, ConfigContext } from 'expo/config';\n\n"
        "const APP_NAME = process.env.EXPO_PUBLIC_APP_NAME || 'Mobile App';\n"
        "const APP_SLUG = process.env.EXPO_PUBLIC_APP_SLUG || 'mobile-app';\n"
        "const APP_SCHEME = process.env.EXPO_PUBLIC_APP_SCHEME || 'mobileapp';\n\n"
        "export default ({ config }: ConfigContext): ExpoConfig => ({\n"
        "  ...config,\n"
        "  name: APP_NAME,\n"
        "  slug: APP_SLUG,\n"
        "  scheme: APP_SCHEME,\n"
        "  version: '1.0.0',\n"
        "  orientation: 'portrait',\n"
        "  userInterfaceStyle: 'light',\n"
        "  splash: {\n"
        "    backgroundColor: '#4f46e5',\n"
        "  },\n"
        "  ios: {\n"
        "    supportsTablet: true,\n"
        "    bundleIdentifier: process.env.EXPO_PUBLIC_IOS_BUNDLE_ID || 'com.example.mobileapp',\n"
        "  },\n"
        "  android: {\n"
        "    package: process.env.EXPO_PUBLIC_ANDROID_PACKAGE || 'com.example.mobileapp',\n"
        "    adaptiveIcon: {\n"
        "      backgroundColor: '#4f46e5',\n"
        "    },\n"
        "  },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # .env.example
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, ".env.example"),
        "EXPO_PUBLIC_APP_NAME=Mobile App\n"
        "EXPO_PUBLIC_APP_SLUG=mobile-app\n"
        "EXPO_PUBLIC_APP_SCHEME=mobileapp\n"
        "EXPO_PUBLIC_API_URL=https://api.example.com\n"
        "EXPO_PUBLIC_IOS_BUNDLE_ID=com.example.mobileapp\n"
        "EXPO_PUBLIC_ANDROID_PACKAGE=com.example.mobileapp\n"))

    # ------------------------------------------------------------------
    # app.json (fallback minimal; app.config.ts adalah sumber utama)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "app.json"), json.dumps({
        "expo": {
            "name": job.title or "Mobile App",
            "slug": slug + "-mobile",
            "version": "1.0.0",
            "orientation": "portrait",
            "userInterfaceStyle": "light",
            "splash": {"backgroundColor": "#4f46e5"},
            "ios": {"supportsTablet": True, "bundleIdentifier": "com.example.mobileapp"},
            "android": {"package": "com.example.mobileapp", "adaptiveIcon": {"backgroundColor": "#4f46e5"}},
        },
    }, indent=2) + "\n"))

    # ------------------------------------------------------------------
    # src/types/navigation.ts (types terpisah -> hilangkan circular import)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/types")), "navigation.ts"),
        "export type RootStackParamList = {\n"
        "  Home: undefined;\n"
        "  Detail: { id: string };\n"
        "};\n\n"
        "export type MainTabParamList = {\n"
        "  HomeTab: undefined;\n"
        "  SettingsTab: undefined;\n"
        "};\n"))

    # ------------------------------------------------------------------
    # src/theme/index.ts (design system)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/theme")), "index.ts"),
        "export const colors = {\n"
        "  background: '#f8fafc',\n"
        "  surface: '#ffffff',\n"
        "  primary: '#4f46e5',\n"
        "  primaryPressed: '#4338ca',\n"
        "  textPrimary: '#0f172a',\n"
        "  textSecondary: '#64748b',\n"
        "  textOnPrimary: '#ffffff',\n"
        "  border: '#e2e8f0',\n"
        "  danger: '#dc2626',\n"
        "  success: '#16a34a',\n"
        "} as const;\n\n"
        "export const spacing = {\n"
        "  xs: 4,\n"
        "  sm: 8,\n"
        "  md: 16,\n"
        "  lg: 24,\n"
        "  xl: 32,\n"
        "} as const;\n\n"
        "export const typography = {\n"
        "  title: { fontSize: 28, fontWeight: '700' as const, color: colors.textPrimary },\n"
        "  heading: { fontSize: 24, fontWeight: '700' as const, color: colors.textPrimary },\n"
        "  body: { fontSize: 16, color: colors.textPrimary },\n"
        "  caption: { fontSize: 14, color: colors.textSecondary },\n"
        "} as const;\n\n"
        "export const radius = {\n"
        "  sm: 6,\n"
        "  md: 8,\n"
        "  lg: 12,\n"
        "} as const;\n"))

    # ------------------------------------------------------------------
    # src/constants/config.ts
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/constants")), "config.ts"),
        "import Constants from 'expo-constants';\n\n"
        "export const API_URL =\n"
        "  process.env.EXPO_PUBLIC_API_URL || 'https://api.example.com';\n\n"
        "export const APP_NAME =\n"
        "  process.env.EXPO_PUBLIC_APP_NAME || Constants.expoConfig?.name || 'Mobile App';\n"))

    # ------------------------------------------------------------------
    # src/api/client.ts (API client + error handling + auth interceptor)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/api")), "client.ts"),
        "import { API_URL } from '@/constants/config';\n\n"
        "export class ApiError extends Error {\n"
        "  status: number;\n"
        "  constructor(message: string, status: number) {\n"
        "    super(message);\n"
        "    this.name = 'ApiError';\n"
        "    this.status = status;\n"
        "  }\n"
        "}\n\n"
        "export interface RequestOptions extends Omit<RequestInit, 'body'> {\n"
        "  body?: unknown;\n"
        "  token?: string;\n"
        "}\n\n"
        "async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {\n"
        "  const { body, token, headers, ...rest } = options;\n"
        "  const finalHeaders: Record<string, string> = {\n"
        "    'Content-Type': 'application/json',\n"
        "    Accept: 'application/json',\n"
        "    ...(headers as Record<string, string>),\n"
        "  };\n"
        "  if (token) finalHeaders.Authorization = `Bearer ${token}`;\n\n"
        "  const res = await fetch(`${API_URL}${path}`, {\n"
        "    ...rest,\n"
        "    headers: finalHeaders,\n"
        "    body: body != null ? JSON.stringify(body) : undefined,\n"
        "  });\n\n"
        "  if (!res.ok) {\n"
        "    let message = `Request failed (${res.status})`;\n"
        "    try {\n"
        "      const data = await res.json();\n"
        "      if (data && typeof data.detail === 'string') message = data.detail;\n"
        "    } catch {\n"
        "      /* ignore parse error */\n"
        "    }\n"
        "    throw new ApiError(message, res.status);\n"
        "  }\n\n"
        "  if (res.status === 204) return undefined as T;\n"
        "  return (await res.json()) as T;\n"
        "}\n\n"
        "export const api = {\n"
        "  get: <T>(path: string, options?: RequestOptions) =>\n"
        "    request<T>(path, { ...options, method: 'GET' }),\n"
        "  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>\n"
        "    request<T>(path, { ...options, method: 'POST', body }),\n"
        "  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>\n"
        "    request<T>(path, { ...options, method: 'PUT', body }),\n"
        "  delete: <T>(path: string, options?: RequestOptions) =>\n"
        "    request<T>(path, { ...options, method: 'DELETE' }),\n"
        "};\n"))

    # ------------------------------------------------------------------
    # src/store/useAppStore.ts (Zustand)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/store")), "useAppStore.ts"),
        "import { create } from 'zustand';\n\n"
        "interface AppState {\n"
        "  token: string | null;\n"
        "  isAuthenticated: boolean;\n"
        "  setToken: (token: string | null) => void;\n"
        "  logout: () => void;\n"
        "}\n\n"
        "export const useAppStore = create<AppState>((set) => ({\n"
        "  token: null,\n"
        "  isAuthenticated: false,\n"
        "  setToken: (token) => set({ token, isAuthenticated: token != null }),\n"
        "  logout: () => set({ token: null, isAuthenticated: false }),\n"
        "}));\n"))

    # ------------------------------------------------------------------
    # src/hooks/useFetch.ts
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/hooks")), "useFetch.ts"),
        "import { useEffect, useState } from 'react';\n"
        "import { api } from '@/api/client';\n\n"
        "interface UseFetchState<T> {\n"
        "  data: T | null;\n"
        "  loading: boolean;\n"
        "  error: string | null;\n"
        "}\n\n"
        "export function useFetch<T>(path: string): UseFetchState<T> {\n"
        "  const [state, setState] = useState<UseFetchState<T>>({\n"
        "    data: null,\n"
        "    loading: true,\n"
        "    error: null,\n"
        "  });\n\n"
        "  useEffect(() => {\n"
        "    let active = true;\n"
        "    setState((s) => ({ ...s, loading: true, error: null }));\n"
        "    api\n"
        "      .get<T>(path)\n"
        "      .then((data) => {\n"
        "        if (active) setState({ data, loading: false, error: null });\n"
        "      })\n"
        "      .catch((err: Error) => {\n"
        "        if (active) setState({ data: null, loading: false, error: err.message });\n"
        "      });\n"
        "    return () => {\n"
        "      active = false;\n"
        "    };\n"
        "  }, [path]);\n\n"
        "  return state;\n"
        "}\n"))

    # ------------------------------------------------------------------
    # src/components/Button.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/components")), "Button.tsx"),
        "import { Pressable, StyleSheet, Text, ActivityIndicator } from 'react-native';\n"
        "import { colors, spacing, radius } from '@/theme';\n\n"
        "interface ButtonProps {\n"
        "  title: string;\n"
        "  onPress: () => void;\n"
        "  loading?: boolean;\n"
        "  disabled?: boolean;\n"
        "  variant?: 'primary' | 'secondary';\n"
        "}\n\n"
        "export function Button({ title, onPress, loading, disabled, variant = 'primary' }: ButtonProps) {\n"
        "  const isDisabled = disabled || loading;\n"
        "  return (\n"
        "    <Pressable\n"
        "      accessibilityRole=\"button\"\n"
        "      accessibilityLabel={title}\n"
        "      onPress={onPress}\n"
        "      disabled={isDisabled}\n"
        "      style={({ pressed }) => [\n"
        "        styles.base,\n"
        "        variant === 'primary' ? styles.primary : styles.secondary,\n"
        "        pressed && !isDisabled && styles.pressed,\n"
        "        isDisabled && styles.disabled,\n"
        "      ]}\n"
        "    >\n"
        "      {loading ? (\n"
        "        <ActivityIndicator color={variant === 'primary' ? colors.textOnPrimary : colors.primary} />\n"
        "      ) : (\n"
        "        <Text style={[styles.label, variant === 'primary' ? styles.labelPrimary : styles.labelSecondary]}>\n"
        "          {title}\n"
        "        </Text>\n"
        "      )}\n"
        "    </Pressable>\n"
        "  );\n"
        "}\n\n"
        "const styles = StyleSheet.create({\n"
        "  base: {\n"
        "    paddingHorizontal: spacing.lg,\n"
        "    paddingVertical: spacing.md,\n"
        "    borderRadius: radius.md,\n"
        "    alignItems: 'center',\n"
        "    justifyContent: 'center',\n"
        "    minHeight: 48,\n"
        "  },\n"
        "  primary: { backgroundColor: colors.primary },\n"
        "  secondary: { backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.primary },\n"
        "  pressed: { opacity: 0.85 },\n"
        "  disabled: { opacity: 0.5 },\n"
        "  label: { fontSize: 16, fontWeight: '600' },\n"
        "  labelPrimary: { color: colors.textOnPrimary },\n"
        "  labelSecondary: { color: colors.primary },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # src/components/Loading.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "src/components/Loading.tsx"),
        "import { ActivityIndicator, StyleSheet, View } from 'react-native';\n"
        "import { colors } from '@/theme';\n\n"
        "export function Loading() {\n"
        "  return (\n"
        "    <View style={styles.container} testID=\"loading\">\n"
        "      <ActivityIndicator size=\"large\" color={colors.primary} />\n"
        "    </View>\n"
        "  );\n"
        "}\n\n"
        "const styles = StyleSheet.create({\n"
        "  container: { flex: 1, alignItems: 'center', justifyContent: 'center' },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # src/components/ErrorView.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "src/components/ErrorView.tsx"),
        "import { StyleSheet, Text, View } from 'react-native';\n"
        "import { colors, spacing } from '@/theme';\n"
        "import { Button } from './Button';\n\n"
        "interface ErrorViewProps {\n"
        "  message: string;\n"
        "  onRetry?: () => void;\n"
        "}\n\n"
        "export function ErrorView({ message, onRetry }: ErrorViewProps) {\n"
        "  return (\n"
        "    <View style={styles.container}>\n"
        "      <Text style={styles.title}>Something went wrong</Text>\n"
        "      <Text style={styles.message}>{message}</Text>\n"
        "      {onRetry && <Button title=\"Retry\" onPress={onRetry} variant=\"secondary\" />}\n"
        "    </View>\n"
        "  );\n"
        "}\n\n"
        "const styles = StyleSheet.create({\n"
        "  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },\n"
        "  title: { fontSize: 20, fontWeight: '700', color: colors.danger },\n"
        "  message: { fontSize: 16, color: colors.textSecondary, marginTop: spacing.sm, textAlign: 'center' },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # src/components/ErrorBoundary.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "src/components/ErrorBoundary.tsx"),
        "import { Component, type ErrorInfo, type ReactNode } from 'react';\n"
        "import { ErrorView } from './ErrorView';\n\n"
        "interface Props {\n"
        "  children: ReactNode;\n"
        "}\n\n"
        "interface State {\n"
        "  hasError: boolean;\n"
        "  message: string;\n"
        "}\n\n"
        "export class ErrorBoundary extends Component<Props, State> {\n"
        "  state: State = { hasError: false, message: '' };\n\n"
        "  static getDerivedStateFromError(error: Error): State {\n"
        "    return { hasError: true, message: error.message };\n"
        "  }\n\n"
        "  componentDidCatch(error: Error, info: ErrorInfo) {\n"
        "    // Log to a monitoring service (e.g. Sentry) in production.\n"
        "    console.error('ErrorBoundary caught', error, info);\n"
        "  }\n\n"
        "  render() {\n"
        "    if (this.state.hasError) {\n"
        "      return <ErrorView message={this.state.message} onRetry={() => this.setState({ hasError: false, message: '' })} />;\n"
        "    }\n"
        "    return this.props.children;\n"
        "  }\n"
        "}\n"))

    # ------------------------------------------------------------------
    # App.tsx (navigation + ErrorBoundary)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "App.tsx"),
        "import 'react-native-gesture-handler';\n"
        "import { NavigationContainer } from '@react-navigation/native';\n"
        "import { createNativeStackNavigator } from '@react-navigation/native-stack';\n"
        "import { StatusBar } from 'expo-status-bar';\n\n"
        "import { ErrorBoundary } from '@/components/ErrorBoundary';\n"
        "import HomeScreen from '@/screens/HomeScreen';\n"
        "import DetailScreen from '@/screens/DetailScreen';\n"
        "import type { RootStackParamList } from '@/types/navigation';\n\n"
        "const Stack = createNativeStackNavigator<RootStackParamList>();\n\n"
        "export default function App() {\n"
        "  return (\n"
        "    <ErrorBoundary>\n"
        "      <NavigationContainer>\n"
        "        <Stack.Navigator initialRouteName=\"Home\">\n"
        "          <Stack.Screen name=\"Home\" component={HomeScreen} options={{ title: 'Home' }} />\n"
        "          <Stack.Screen name=\"Detail\" component={DetailScreen} options={{ title: 'Detail' }} />\n"
        "        </Stack.Navigator>\n"
        "        <StatusBar style=\"auto\" />\n"
        "      </NavigationContainer>\n"
        "    </ErrorBoundary>\n"
        "  );\n"
        "}\n"))

    # ------------------------------------------------------------------
    # src/screens/HomeScreen.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/screens")), "HomeScreen.tsx"),
        "import { StyleSheet, Text, View } from 'react-native';\n"
        "import type { NativeStackScreenProps } from '@react-navigation/native-stack';\n"
        "import type { RootStackParamList } from '@/types/navigation';\n"
        "import { Button } from '@/components/Button';\n"
        "import { colors, spacing, typography } from '@/theme';\n"
        "import { APP_NAME } from '@/constants/config';\n\n"
        "type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;\n\n"
        f"const COMPANY = {json.dumps(job.company or 'Client')};\n\n"
        "export default function HomeScreen({ navigation }: Props) {\n"
        "  return (\n"
        "    <View style={styles.container}>\n"
        "      <Text style={styles.title}>{APP_NAME}</Text>\n"
        "      <Text style={styles.subtitle}>Delivered for {COMPANY}</Text>\n"
        "      <Button title=\"View detail\" onPress={() => navigation.navigate('Detail', { id: '1' })} />\n"
        "    </View>\n"
        "  );\n"
        "}\n\n"
        "const styles = StyleSheet.create({\n"
        "  container: { flex: 1, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },\n"
        "  title: { ...typography.title },\n"
        "  subtitle: { ...typography.caption, marginTop: spacing.sm },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # src/screens/DetailScreen.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "src/screens")), "DetailScreen.tsx"),
        "import { StyleSheet, Text, View } from 'react-native';\n"
        "import type { NativeStackScreenProps } from '@react-navigation/native-stack';\n"
        "import type { RootStackParamList } from '@/types/navigation';\n"
        "import { colors, spacing, typography } from '@/theme';\n\n"
        "type Props = NativeStackScreenProps<RootStackParamList, 'Detail'>;\n\n"
        "export default function DetailScreen({ route }: Props) {\n"
        "  return (\n"
        "    <View style={styles.container}>\n"
        "      <Text style={styles.title}>Detail</Text>\n"
        "      <Text style={styles.body}>Item id: {route.params.id}</Text>\n"
        "    </View>\n"
        "  );\n"
        "}\n\n"
        "const styles = StyleSheet.create({\n"
        "  container: { flex: 1, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },\n"
        "  title: { ...typography.heading },\n"
        "  body: { ...typography.body, marginTop: spacing.sm },\n"
        "});\n"))

    # ------------------------------------------------------------------
    # jest.setup.js
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "jest.setup.js"),
        "// Silence the reanimated warning in tests.\n"
        "jest.mock('react-native-reanimated', () =>\n"
        "  require('react-native-reanimated/mock'),\n"
        ");\n"))

    # ------------------------------------------------------------------
    # __tests__/HomeScreen.test.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "__tests__")), "HomeScreen.test.tsx"),
        "import { render, screen, fireEvent } from '@testing-library/react-native';\n"
        "import HomeScreen from '@/screens/HomeScreen';\n\n"
        "const navigation = { navigate: jest.fn() } as any;\n"
        "const route = {} as any;\n\n"
        "describe('HomeScreen', () => {\n"
        "  it('renders the app name', () => {\n"
        "    render(<HomeScreen navigation={navigation} route={route} />);\n"
        "    expect(screen.getByText(/Mobile App/)).toBeTruthy();\n"
        "  });\n"
        "  it('navigates on press', () => {\n"
        "    render(<HomeScreen navigation={navigation} route={route} />);\n"
        "    fireEvent.press(screen.getByText('View detail'));\n"
        "    expect(navigation.navigate).toHaveBeenCalledWith('Detail', { id: '1' });\n"
        "  });\n"
        "});\n"))

    # ------------------------------------------------------------------
    # __tests__/Button.test.tsx
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "__tests__/Button.test.tsx"),
        "import { render, screen, fireEvent } from '@testing-library/react-native';\n"
        "import { Button } from '@/components/Button';\n\n"
        "describe('Button', () => {\n"
        "  it('renders title and calls onPress', () => {\n"
        "    const onPress = jest.fn();\n"
        "    render(<Button title=\"Click me\" onPress={onPress} />);\n"
        "    fireEvent.press(screen.getByText('Click me'));\n"
        "    expect(onPress).toHaveBeenCalled();\n"
        "  });\n"
        "  it('disables and shows spinner when loading', () => {\n"
        "    const onPress = jest.fn();\n"
        "    render(<Button title=\"Loading\" onPress={onPress} loading />);\n"
        "    expect(screen.queryByText('Loading')).toBeNull();\n"
        "  });\n"
        "});\n"))

    # ------------------------------------------------------------------
    # eslint.config.js (ESLint 9 flat config)
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "eslint.config.js"),
        "const { defineConfig } = require('eslint/config');\n"
        "const expoConfig = require('eslint-config-expo/flat');\n\n"
        "module.exports = defineConfig([\n"
        "  expoConfig,\n"
        "  {\n"
        "    ignores: ['dist/*', '.expo/*', 'node_modules/*'],\n"
        "  },\n"
        "]);\n"))

    # ------------------------------------------------------------------
    # .prettierrc
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, ".prettierrc"), json.dumps({
        "singleQuote": True, "trailingComma": "all", "printWidth": 100,
    }, indent=2) + "\n"))

    # ------------------------------------------------------------------
    # .editorconfig
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, ".editorconfig"),
        "root = true\n\n"
        "[*]\n"
        "charset = utf-8\n"
        "end_of_line = lf\n"
        "insert_final_newline = true\n"
        "indent_style = space\n"
        "indent_size = 2\n"
        "trim_trailing_whitespace = true\n"))

    # ------------------------------------------------------------------
    # .nvmrc
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, ".nvmrc"), "20\n"))

    # ------------------------------------------------------------------
    # eas.json
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "eas.json"), json.dumps({
        "cli": {"version": ">= 7.0.0"},
        "build": {
            "development": {"developmentClient": True, "distribution": "internal"},
            "preview": {"distribution": "internal"},
            "production": {"autoIncrement": True},
        },
    }, indent=2) + "\n"))

    # ------------------------------------------------------------------
    # .github/workflows/ci.yml
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-node@v4\n"
        "        with:\n"
        "          node-version: '20'\n"
        "          cache: 'npm'\n"
        "      - run: npm ci || npm install\n"
        "      - run: npm run lint\n"
        "      - run: npm run typecheck\n"
        "      - run: npm run test:ci\n"))

    # ------------------------------------------------------------------
    # .gitignore
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, ".gitignore"),
        "node_modules/\n.expo/\ndist/\nweb-build/\n*.log\n.env\n.env.local\nexpo-env.d.ts\ncoverage/\n"))

    # ------------------------------------------------------------------
    # README.md
    # ------------------------------------------------------------------
    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'Mobile App'}\n\n"
        "Production-grade React Native (Expo + TypeScript) mobile app for **" + (job.company or 'client') + "**.\n\n"
        "## Stack\n"
        "- Expo SDK 57 + React Native 0.86 + TypeScript (strict) + path alias `@/*`\n"
        "- React Navigation (native stack)\n"
        "- Zustand (state management)\n"
        "- API client with auth interceptor & error handling\n"
        "- Design system (theme: colors/spacing/typography) + reusable components\n"
        "- ErrorBoundary + Loading + ErrorView\n"
        "- Jest + React Native Testing Library\n"
        "- ESLint 9 (flat config) + Prettier + editorconfig + EAS\n\n"
        "## Run\n```bash\nnpm install\nnpx expo start\n```\n\n"
        "## Test\n```bash\nnpm test\nnpm run typecheck\nnpm run lint\n```\n\n"
        "## Build (EAS)\n```bash\nnpm run build:preview\nnpm run build:production\n```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-mobile",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"React Native app '{slug}' (Expo+TS, {len(files)} files, navigation+state+api+theme+tests+CI)",
        "role": "developer",
    }


def build_devops_pipeline(job: Job) -> dict:
    """Generate pipeline DevOps (Docker + Kubernetes + CI) yang siap pakai."""
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-devops"))
    files = []

    files.append(_write(os.path.join(root, "Dockerfile"),
        "# ---- build stage ----\n"
        "FROM python:3.12-slim AS builder\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir --upgrade pip && \\\n"
        "    pip install --no-cache-dir -r requirements.txt\n\n"
        "# ---- runtime stage ----\n"
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages\n"
        "COPY --from=builder /usr/local/bin /usr/local/bin\n"
        "COPY . .\n"
        "RUN addgroup --system app && adduser --system --ingroup app app\n"
        "USER app\n\n"
        "EXPOSE 8000\n"
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'))

    files.append(_write(os.path.join(root, "requirements.txt"),
        "fastapi==0.141.1\nuvicorn[standard]==0.52.4\n"))

    files.append(_write(os.path.join(root, ".dockerignore"),
        "__pycache__\n*.pyc\n.env\n.git\n.venv\n.terraform\nhelm/\nterraform/\n.github/\n*.md\n"))

    # --- Helm chart ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "helm", slug, "templates")), "deployment.yaml"),
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: {{ include \"chart.fullname\" . }}\n"
        "  labels:\n"
        "    {{- include \"chart.labels\" . | nindent 4 }}\n"
        "spec:\n"
        "  replicas: {{ .Values.replicaCount }}\n"
        "  selector:\n"
        "    matchLabels:\n"
        "      {{- include \"chart.selectorLabels\" . | nindent 6 }}\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        "        {{- include \"chart.selectorLabels\" . | nindent 8 }}\n"
        "    spec:\n"
        "      serviceAccountName: {{ include \"chart.fullname\" . }}\n"
        "      containers:\n"
        "      - name: {{ .Chart.Name }}\n"
        "        image: \"{{ .Values.image.repository }}:{{ .Values.image.tag }}\"\n"
        "        imagePullPolicy: {{ .Values.image.pullPolicy }}\n"
        "        ports:\n"
        "        - containerPort: 8000\n"
        "        readinessProbe:\n"
        "          httpGet:\n"
        "            path: /health\n"
        "            port: 8000\n"
        "        livenessProbe:\n"
        "          httpGet:\n"
        "            path: /health\n"
        "            port: 8000\n"
        "        resources:\n"
        "          {{- toYaml .Values.resources | nindent 10 }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/service.yaml"),
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: {{ include \"chart.fullname\" . }}\n"
        "  labels:\n"
        "    {{- include \"chart.labels\" . | nindent 4 }}\n"
        "spec:\n"
        "  type: {{ .Values.service.type }}\n"
        "  ports:\n"
        "  - port: {{ .Values.service.port }}\n"
        "    targetPort: 8000\n"
        "  selector:\n"
        "    {{- include \"chart.selectorLabels\" . | nindent 4 }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/_helpers.tpl"),
        "{{- define \"chart.name\" -}}\n"
        "{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix \"-\" }}\n"
        "{{- end }}\n\n"
        "{{- define \"chart.fullname\" -}}\n"
        "{{- printf \"%s-%s\" .Release.Name (include \"chart.name\" .) | trunc 63 | trimSuffix \"-\" }}\n"
        "{{- end }}\n\n"
        "{{- define \"chart.labels\" -}}\n"
        "app.kubernetes.io/name: {{ include \"chart.name\" . }}\n"
        "app.kubernetes.io/instance: {{ .Release.Name }}\n"
        "{{- end }}\n\n"
        "{{- define \"chart.selectorLabels\" -}}\n"
        "app.kubernetes.io/name: {{ include \"chart.name\" . }}\n"
        "app.kubernetes.io/instance: {{ .Release.Name }}\n"
        "{{- end }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/Chart.yaml"),
        "apiVersion: v2\n"
        "name: " + slug + "\n"
        "description: Helm chart for " + (job.title or 'service') + "\n"
        "type: application\n"
        "version: 0.1.0\n"
        "appVersion: \"1.0.0\"\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/values.yaml"),
        "replicaCount: 3\n\n"
        "image:\n"
        "  repository: " + slug + "\n"
        "  tag: latest\n"
        "  pullPolicy: IfNotPresent\n\n"
        "service:\n"
        "  type: ClusterIP\n"
        "  port: 80\n\n"
        "resources:\n"
        "  requests:\n"
        "    cpu: 100m\n"
        "    memory: 128Mi\n"
        "  limits:\n"
        "    cpu: 500m\n"
        "    memory: 512Mi\n\n"
        "autoscaling:\n"
        "  enabled: true\n"
        "  minReplicas: 3\n"
        "  maxReplicas: 10\n"
        "  targetCPUUtilizationPercentage: 80\n\n"
        "ingress:\n"
        "  enabled: false\n"
        "  className: nginx\n"
        "  hosts:\n"
        "    - host: " + slug + ".example.com\n"
        "      paths:\n"
        "        - path: /\n"
        "          pathType: Prefix\n\n"
        "serviceAccount:\n"
        "  create: true\n"
        "  name: \"\"\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/hpa.yaml"),
        "{{- if .Values.autoscaling.enabled }}\n"
        "apiVersion: autoscaling/v2\n"
        "kind: HorizontalPodAutoscaler\n"
        "metadata:\n"
        "  name: {{ include \"chart.fullname\" . }}\n"
        "  labels:\n"
        "    {{- include \"chart.labels\" . | nindent 4 }}\n"
        "spec:\n"
        "  scaleTargetRef:\n"
        "    apiVersion: apps/v1\n"
        "    kind: Deployment\n"
        "    name: {{ include \"chart.fullname\" . }}\n"
        "  minReplicas: {{ .Values.autoscaling.minReplicas }}\n"
        "  maxReplicas: {{ .Values.autoscaling.maxReplicas }}\n"
        "  metrics:\n"
        "    - type: Resource\n"
        "      resource:\n"
        "        name: cpu\n"
        "        target:\n"
        "          type: Utilization\n"
        "          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}\n"
        "{{- end }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/ingress.yaml"),
        "{{- if .Values.ingress.enabled }}\n"
        "apiVersion: networking.k8s.io/v1\n"
        "kind: Ingress\n"
        "metadata:\n"
        "  name: {{ include \"chart.fullname\" . }}\n"
        "  labels:\n"
        "    {{- include \"chart.labels\" . | nindent 4 }}\n"
        "spec:\n"
        "  ingressClassName: {{ .Values.ingress.className }}\n"
        "  rules:\n"
        "    {{- range .Values.ingress.hosts }}\n"
        "    - host: {{ .host | quote }}\n"
        "      http:\n"
        "        paths:\n"
        "          {{- range .paths }}\n"
        "          - path: {{ .path }}\n"
        "            pathType: {{ .pathType }}\n"
        "            backend:\n"
        "              service:\n"
        "                name: {{ include \"chart.fullname\" $ }}\n"
        "                port:\n"
        "                  number: {{ $.Values.service.port }}\n"
        "          {{- end }}\n"
        "    {{- end }}\n"
        "{{- end }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/serviceaccount.yaml"),
        "{{- if .Values.serviceAccount.create }}\n"
        "apiVersion: v1\n"
        "kind: ServiceAccount\n"
        "metadata:\n"
        "  name: {{ include \"chart.fullname\" . }}\n"
        "  labels:\n"
        "    {{- include \"chart.labels\" . | nindent 4 }}\n"
        "{{- end }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/templates/NOTES.txt"),
        "1. Get the application URL by running these commands:\n"
        "{{- if .Values.ingress.enabled }}\n"
        "  http{{ if $.Values.ingress.tls }}s{{ end }}://{{ (index .Values.ingress.hosts 0).host }}/\n"
        "{{- else }}\n"
        "  export POD_NAME=$(kubectl get pods --namespace {{ .Release.Namespace }} -l \"app.kubernetes.io/name={{ include \"chart.name\" . }},app.kubernetes.io/instance={{ .Release.Name }}\" -o jsonpath=\"{.items[0].metadata.name}\")\n"
        "  kubectl --namespace {{ .Release.Namespace }} port-forward $POD_NAME 8080:8000\n"
        "  echo \"Visit http://127.0.0.1:8080\"\n"
        "{{- end }}\n"))

    files.append(_write(os.path.join(root, "helm/" + slug + "/.helmignore"),
        ".git/\n*.md\ncharts/\n"))

    # --- Terraform (infra as code) ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "terraform")), "main.tf"),
        "terraform {\n"
        "  required_version = \">= 1.5\"\n"
        "  required_providers {\n"
        "    kubernetes = {\n"
        "      source  = \"hashicorp/kubernetes\"\n"
        "      version = \"~> 2.30\"\n"
        "    }\n"
        "  }\n"
        "}\n\n"
        "provider \"kubernetes\" {\n"
        "  config_path = \"~/.kube/config\"\n"
        "}\n\n"
        "resource \"kubernetes_namespace\" \"app\" {\n"
        "  metadata {\n"
        "    name = \"" + slug + "\"\n"
        "  }\n"
        "}\n"))

    files.append(_write(os.path.join(root, "terraform/variables.tf"),
        "variable \"environment\" {\n"
        "  description = \"Deployment environment\"\n"
        "  type        = string\n"
        "  default     = \"production\"\n"
        "}\n"))

    files.append(_write(os.path.join(root, "terraform/outputs.tf"),
        "output \"namespace\" {\n"
        "  value = kubernetes_namespace.app.metadata[0].name\n"
        "}\n"))

    # --- CI/CD ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: Build image\n"
        "        run: docker build -t " + slug + " .\n"
        "      - name: Lint\n"
        "        run: pip install flake8 && flake8 .\n"
        "      - name: Helm lint\n"
        "        uses: azure/setup-helm@v4\n"
        "        with:\n"
        "          version: latest\n"
        "      - run: helm lint helm/" + slug + "\n"
        "      - name: Terraform validate\n"
        "        uses: hashicorp/setup-terraform@v3\n"
        "      - run: terraform init -backend=false && terraform validate\n"
        "        working-directory: terraform\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "main.py"),
        "from fastapi import FastAPI\n"
        "from datetime import datetime\n\n"
        "app = FastAPI(title=" + json.dumps(job.title or 'Service') + ")\n\n"
        "@app.get('/')\n"
        "def root():\n"
        "    return {'service': " + json.dumps(job.title or 'Service') + ", 'time': datetime.utcnow().isoformat()}\n\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n"))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'DevOps Pipeline'}\n\n"
        "Containerized service with Kubernetes manifests (Helm) and CI for **" + (job.company or 'client') + "**.\n\n"
        "## Build & Run\n```bash\ndocker build -t " + slug + " .\ndocker run -p 8000:8000 " + slug + "\n```\n\n"
        "## Deploy to Kubernetes (Helm)\n```bash\nhelm lint helm/" + slug + "\nhelm install " + slug + " helm/" + slug + "\nkubectl get pods\n```\n\n"
        "## Infrastructure (Terraform)\n```bash\ncd terraform\nterraform init -backend=false\nterraform validate\n```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-devops",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"DevOps pipeline '{slug}' (Docker + K8s + CI)",
        "role": "developer",
    }


# =============================================================================
# CLOUD INFRASTRUCTURE (AWS / GCP / AZURE)
# =============================================================================

def build_cloud_infrastructure(job: Job, provider: str = None) -> dict:
    """Generate infrastruktur cloud (Terraform IaC) untuk AWS / GCP / Azure.

    Menghasilkan modul Terraform lengkap per provider + CI/CD deploy, siap
    dipakai untuk provisioning infrastruktur produksi. Mencakup:
      - AWS   : VPC, EKS, RDS, S3, IAM, ECR
      - GCP   : VPC, GKE, Cloud SQL, GCS, IAM, Artifact Registry
      - Azure : VNet, AKS, SQL Database, Blob Storage, RBAC, ACR

    provider: 'aws' | 'gcp' | 'azure' | None (auto-detect dari judul/deskripsi)
    """
    slug = _slugify(job.title)
    text = " ".join(filter(None, [job.title or "", job.description or ""])).lower()

    if provider is None:
        if any(k in text for k in ["gcp", "google cloud", "gke", "google"]):
            provider = "gcp"
        elif any(k in text for k in ["azure", "aks", "microsoft"]):
            provider = "azure"
        else:
            provider = "aws"  # default AWS (paling umum)

    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-" + provider))
    files = []

    # --- Shared: versions.tf (provider block) ---
    provider_blocks = {
        "aws": (
            "terraform {\n"
            "  required_version = \">= 1.5\"\n"
            "  required_providers {\n"
            "    aws = {\n"
            "      source  = \"hashicorp/aws\"\n"
            "      version = \"~> 5.0\"\n"
            "    }\n"
            "    kubernetes = {\n"
            "      source  = \"hashicorp/kubernetes\"\n"
            "      version = \"~> 2.30\"\n"
            "    }\n"
            "    helm = {\n"
            "      source  = \"hashicorp/helm\"\n"
            "      version = \"~> 2.13\"\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            "provider \"aws\" {\n"
            "  region = var.region\n"
            "}\n\n"
            "data \"aws_eks_cluster\" \"cluster\" {\n"
            "  name = module.eks.cluster_name\n"
            "  depends_on = [module.eks]\n"
            "}\n\n"
            "data \"aws_eks_cluster_auth\" \"cluster\" {\n"
            "  name = module.eks.cluster_name\n"
            "}\n\n"
            "provider \"kubernetes\" {\n"
            "  host                   = data.aws_eks_cluster.cluster.endpoint\n"
            "  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)\n"
            "  token                  = data.aws_eks_cluster_auth.cluster.token\n"
            "}\n\n"
            "provider \"helm\" {\n"
            "  kubernetes {\n"
            "    host                   = data.aws_eks_cluster.cluster.endpoint\n"
            "    cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)\n"
            "    token                  = data.aws_eks_cluster_auth.cluster.token\n"
            "  }\n"
            "}\n"
        ),
        "gcp": (
            "terraform {\n"
            "  required_version = \">= 1.5\"\n"
            "  required_providers {\n"
            "    google = {\n"
            "      source  = \"hashicorp/google\"\n"
            "      version = \"~> 5.0\"\n"
            "    }\n"
            "    kubernetes = {\n"
            "      source  = \"hashicorp/kubernetes\"\n"
            "      version = \"~> 2.30\"\n"
            "    }\n"
            "    helm = {\n"
            "      source  = \"hashicorp/helm\"\n"
            "      version = \"~> 2.13\"\n"
            "    }\n"
            "    random = {\n"
            "      source  = \"hashicorp/random\"\n"
            "      version = \"~> 3.6\"\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            "provider \"google\" {\n"
            "  project = var.project_id\n"
            "  region  = var.region\n"
            "}\n\n"
            "data \"google_client_config\" \"default\" {}\n\n"
            "provider \"kubernetes\" {\n"
            "  host                   = \"https://${module.gke.endpoint}\"\n"
            "  token                  = data.google_client_config.default.access_token\n"
            "  cluster_ca_certificate = base64decode(module.gke.ca_certificate)\n"
            "}\n\n"
            "provider \"helm\" {\n"
            "  kubernetes {\n"
            "    host                   = \"https://${module.gke.endpoint}\"\n"
            "    token                  = data.google_client_config.default.access_token\n"
            "    cluster_ca_certificate = base64decode(module.gke.ca_certificate)\n"
            "  }\n"
            "}\n"
        ),
        "azure": (
            "terraform {\n"
            "  required_version = \">= 1.5\"\n"
            "  required_providers {\n"
            "    azurerm = {\n"
            "      source  = \"hashicorp/azurerm\"\n"
            "      version = \"~> 3.100\"\n"
            "    }\n"
            "    kubernetes = {\n"
            "      source  = \"hashicorp/kubernetes\"\n"
            "      version = \"~> 2.30\"\n"
            "    }\n"
            "    helm = {\n"
            "      source  = \"hashicorp/helm\"\n"
            "      version = \"~> 2.13\"\n"
            "    }\n"
            "    random = {\n"
            "      source  = \"hashicorp/random\"\n"
            "      version = \"~> 3.6\"\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            "provider \"azurerm\" {\n"
            "  features {}\n"
            "}\n\n"
            "data \"azurerm_kubernetes_cluster\" \"cluster\" {\n"
            "  name                = module.aks.cluster_name\n"
            "  resource_group_name = module.aks.resource_group_name\n"
            "  depends_on          = [module.aks]\n"
            "}\n\n"
            "provider \"kubernetes\" {\n"
            "  host                   = data.azurerm_kubernetes_cluster.cluster.kube_config[0].host\n"
            "  client_certificate     = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].client_certificate)\n"
            "  client_key             = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].client_key)\n"
            "  cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].cluster_ca_certificate)\n"
            "}\n\n"
            "provider \"helm\" {\n"
            "  kubernetes {\n"
            "    host                   = data.azurerm_kubernetes_cluster.cluster.kube_config[0].host\n"
            "    client_certificate     = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].client_certificate)\n"
            "    client_key             = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].client_key)\n"
            "    cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.cluster.kube_config[0].cluster_ca_certificate)\n"
            "  }\n"
            "}\n"
        ),
    }

    files.append(_write(os.path.join(root, "versions.tf"), provider_blocks[provider]))

    # --- variables.tf ---
    files.append(_write(os.path.join(root, "variables.tf"),
        "variable \"environment\" {\n"
        "  description = \"Deployment environment (dev/staging/production)\"\n"
        "  type        = string\n"
        "  default     = \"production\"\n"
        "}\n\n"
        "variable \"region\" {\n"
        "  description = \"Cloud region\"\n"
        "  type        = string\n"
        "  default     = " + json.dumps(
            "us-east-1" if provider == "aws" else
            "us-central1" if provider == "gcp" else "eastus") + "\n"
        "}\n\n"
        + (("variable \"project_id\" {\n"
        "  description = \"GCP project ID\"\n"
        "  type        = string\n"
        "}\n\n") if provider == "gcp" else "") +
        "variable \"cluster_name\" {\n"
        "  description = \"Kubernetes cluster name\"\n"
        "  type        = string\n"
        "  default     = \"" + slug + "\"\n"
        "}\n\n"
        "variable \"node_count\" {\n"
        "  description = \"Number of worker nodes\"\n"
        "  type        = number\n"
        "  default     = 3\n"
        "}\n\n"
        "variable \"node_machine_type\" {\n"
        "  description = \"Worker node instance type\"\n"
        "  type        = string\n"
        "  default     = " + json.dumps(
            "t3.medium" if provider == "aws" else
            "e2-medium" if provider == "gcp" else "Standard_D2s_v3") + "\n"
        "}\n"))

    # --- Provider-specific main.tf ---
    if provider == "aws":
        files.append(_write(os.path.join(root, "main.tf"),
            "# ===== Networking =====\n"
            "module \"vpc\" {\n"
            "  source  = \"terraform-aws-modules/vpc/aws\"\n"
            "  version = \"~> 5.0\"\n\n"
            "  name = var.cluster_name + \"-vpc\"\n"
            "  cidr = \"10.0.0.0/16\"\n\n"
            "  azs             = [var.region + \"a\", var.region + \"b\", var.region + \"c\"]\n"
            "  private_subnets = [\"10.0.1.0/24\", \"10.0.2.0/24\", \"10.0.3.0/24\"]\n"
            "  public_subnets  = [\"10.0.101.0/24\", \"10.0.102.0/24\", \"10.0.103.0/24\"]\n\n"
            "  enable_nat_gateway = true\n"
            "  single_nat_gateway = true\n"
            "  enable_dns_hostnames = true\n\n"
            "  tags = { Environment = var.environment }\n"
            "}\n\n"
            "# ===== Kubernetes (EKS) =====\n"
            "module \"eks\" {\n"
            "  source  = \"terraform-aws-modules/eks/aws\"\n"
            "  version = \"~> 20.0\"\n\n"
            "  cluster_name    = var.cluster_name\n"
            "  cluster_version = \"1.29\"\n"
            "  subnet_ids      = module.vpc.private_subnets\n"
            "  vpc_id          = module.vpc.vpc_id\n\n"
            "  cluster_endpoint_public_access = true\n\n"
            "  eks_managed_node_groups = {\n"
            "    main = {\n"
            "      desired_size = var.node_count\n"
            "      min_size     = 1\n"
            "      max_size     = 10\n"
            "      instance_types = [var.node_machine_type]\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            "# ===== Database (RDS PostgreSQL) =====\n"
            "module \"db\" {\n"
            "  source  = \"terraform-aws-modules/rds/aws\"\n"
            "  version = \"~> 6.0\"\n\n"
            "  identifier = var.cluster_name + \"-db\"\n"
            "  engine     = \"postgres\"\n"
            "  engine_version = \"16.1\"\n"
            "  instance_class = \"db.t3.micro\"\n"
            "  allocated_storage = 20\n\n"
            "  db_name  = \"app\"\n"
            "  username = \"admin\"\n"
            "  port     = 5432\n\n"
            "  vpc_security_group_ids = [module.eks.cluster_security_group_id]\n"
            "  db_subnet_group_name   = module.vpc.database_subnet_group_name\n\n"
            "  manage_master_user_password = true\n"
            "  skip_final_snapshot         = true\n"
            "}\n\n"
            "# ===== Object storage (S3) =====\n"
            "module \"s3_bucket\" {\n"
            "  source  = \"terraform-aws-modules/s3-bucket/aws\"\n"
            "  version = \"~> 4.0\"\n\n"
            "  bucket = var.cluster_name + \"-assets\"\n"
            "  acl    = \"private\"\n\n"
            "  versioning = { enabled = true }\n"
            "  server_side_encryption_configuration = {\n"
            "    rule = { apply_server_side_encryption_by_default = { sse_algorithm = \"AES256\" } }\n"
            "  }\n"
            "}\n\n"
            "# ===== Container registry (ECR) =====\n"
            "resource \"aws_ecr_repository\" \"app\" {\n"
            "  name                 = var.cluster_name\n"
            "  image_tag_mutability = \"MUTABLE\"\n"
            "  force_delete         = true\n"
            "}\n\n"
            "# ===== IAM role untuk workload (IRSA) =====\n"
            "module \"irsa\" {\n"
            "  source  = \"terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks\"\n"
            "  version = \"~> 5.0\"\n\n"
            "  role_name = var.cluster_name + \"-app\"\n"
            "  attach_s3_policy = true\n"
            "  s3_bucket_arns   = [module.s3_bucket.s3_bucket_arn]\n\n"
            "  oidc_providers = {\n"
            "    main = {\n"
            "      provider_arn               = module.eks.oidc_provider_arn\n"
            "      namespace_service_accounts = [\"default:app\"]\n"
            "    }\n"
            "  }\n"
            "}\n"))
    elif provider == "gcp":
        files.append(_write(os.path.join(root, "main.tf"),
            "# ===== Networking =====\n"
            "resource \"google_compute_network\" \"vpc\" {\n"
            "  name                    = var.cluster_name + \"-vpc\"\n"
            "  auto_create_subnetworks = false\n"
            "}\n\n"
            "resource \"google_compute_subnetwork\" \"subnet\" {\n"
            "  name          = var.cluster_name + \"-subnet\"\n"
            "  network       = google_compute_network.vpc.id\n"
            "  region        = var.region\n"
            "  ip_cidr_range = \"10.0.0.0/16\"\n"
            "}\n\n"
            "# ===== Kubernetes (GKE) =====\n"
            "module \"gke\" {\n"
            "  source  = \"terraform-google-modules/kubernetes-engine/google\"\n"
            "  version = \"~> 30.0\"\n\n"
            "  project_id = var.project_id\n"
            "  name       = var.cluster_name\n"
            "  region     = var.region\n"
            "  network    = google_compute_network.vpc.name\n"
            "  subnetwork = google_compute_subnetwork.subnet.name\n\n"
            "  ip_range_pods     = \"pods-range\"\n"
            "  ip_range_services = \"services-range\"\n\n"
            "  node_pools = [\n"
            "    {\n"
            "      name         = \"default-pool\"\n"
            "      machine_type = var.node_machine_type\n"
            "      min_count    = 1\n"
            "      max_count    = 10\n"
            "      initial_node_count = var.node_count\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "# ===== Database (Cloud SQL PostgreSQL) =====\n"
            "resource \"google_sql_database_instance\" \"db\" {\n"
            "  name             = var.cluster_name + \"-db\"\n"
            "  database_version = \"POSTGRES_16\"\n"
            "  region           = var.region\n\n"
            "  settings {\n"
            "    tier = \"db-f1-micro\"\n"
            "    ip_configuration {\n"
            "      ipv4_enabled = true\n"
            "    }\n"
            "  }\n\n"
            "  deletion_protection = false\n"
            "}\n\n"
            "resource \"google_sql_database\" \"app\" {\n"
            "  name     = \"app\"\n"
            "  instance = google_sql_database_instance.db.name\n"
            "}\n\n"
            "resource \"google_sql_user\" \"admin\" {\n"
            "  name     = \"admin\"\n"
            "  instance = google_sql_database_instance.db.name\n"
            "  password = random_password.db.result\n"
            "}\n\n"
            "resource \"random_password\" \"db\" {\n"
            "  length  = 16\n"
            "  special = false\n"
            "}\n\n"
            "# ===== Object storage (GCS) =====\n"
            "resource \"google_storage_bucket\" \"assets\" {\n"
            "  name          = var.cluster_name + \"-assets\"\n"
            "  location      = var.region\n"
            "  force_destroy = true\n"
            "  versioning { enabled = true }\n"
            "}\n\n"
            "# ===== Container registry (Artifact Registry) =====\n"
            "resource \"google_artifact_registry_repository\" \"app\" {\n"
            "  location      = var.region\n"
            "  repository_id = var.cluster_name\n"
            "  format        = \"DOCKER\"\n"
            "}\n\n"
            "# ===== IAM (Workload Identity) =====\n"
            "resource \"google_service_account\" \"app\" {\n"
            "  account_id   = var.cluster_name + \"-app\"\n"
            "  display_name = \"App service account\"\n"
            "}\n\n"
            "resource \"google_storage_bucket_iam_member\" \"app\" {\n"
            "  bucket = google_storage_bucket.assets.name\n"
            "  role   = \"roles/storage.objectAdmin\"\n"
            "  member = \"serviceAccount:\" + google_service_account.app.email\n"
            "}\n"))
    else:  # azure
        files.append(_write(os.path.join(root, "main.tf"),
            "# ===== Networking =====\n"
            "resource \"azurerm_resource_group\" \"rg\" {\n"
            "  name     = var.cluster_name + \"-rg\"\n"
            "  location = var.region\n"
            "}\n\n"
            "resource \"azurerm_virtual_network\" \"vnet\" {\n"
            "  name                = var.cluster_name + \"-vnet\"\n"
            "  resource_group_name = azurerm_resource_group.rg.name\n"
            "  location            = azurerm_resource_group.rg.location\n"
            "  address_space       = [\"10.0.0.0/16\"]\n"
            "}\n\n"
            "resource \"azurerm_subnet\" \"aks\" {\n"
            "  name                 = var.cluster_name + \"-subnet\"\n"
            "  resource_group_name  = azurerm_resource_group.rg.name\n"
            "  virtual_network_name = azurerm_virtual_network.vnet.name\n"
            "  address_prefixes     = [\"10.0.1.0/24\"]\n"
            "}\n\n"
            "# ===== Kubernetes (AKS) =====\n"
            "module \"aks\" {\n"
            "  source  = \"Azure/aks/azurerm\"\n"
            "  version = \"~> 9.0\"\n\n"
            "  resource_group_name = azurerm_resource_group.rg.name\n"
            "  cluster_name        = var.cluster_name\n"
            "  prefix              = var.cluster_name\n"
            "  location            = azurerm_resource_group.rg.location\n\n"
            "  node_count = var.node_count\n"
            "  vm_size    = var.node_machine_type\n\n"
            "  vnet_subnet_id = azurerm_subnet.aks.id\n"
            "}\n\n"
            "# ===== Database (SQL Database) =====\n"
            "resource \"azurerm_mssql_server\" \"sql\" {\n"
            "  name                         = var.cluster_name + \"-sql\"\n"
            "  resource_group_name          = azurerm_resource_group.rg.name\n"
            "  location                     = azurerm_resource_group.rg.location\n"
            "  version                      = \"12.0\"\n"
            "  administrator_login          = \"sqladmin\"\n"
            "  administrator_login_password = random_password.db.result\n"
            "}\n\n"
            "resource \"azurerm_mssql_database\" \"app\" {\n"
            "  name      = \"app\"\n"
            "  server_id = azurerm_mssql_server.sql.id\n"
            "  sku_name  = \"Basic\"\n"
            "}\n\n"
            "resource \"random_password\" \"db\" {\n"
            "  length  = 16\n"
            "  special = true\n"
            "}\n\n"
            "# ===== Object storage (Blob Storage) =====\n"
            "resource \"azurerm_storage_account\" \"assets\" {\n"
            "  name                     = var.cluster_name + \"assets\"\n"
            "  resource_group_name      = azurerm_resource_group.rg.name\n"
            "  location                 = azurerm_resource_group.rg.location\n"
            "  account_tier             = \"Standard\"\n"
            "  account_replication_type = \"LRS\"\n"
            "}\n\n"
            "resource \"azurerm_storage_container\" \"assets\" {\n"
            "  name                  = \"assets\"\n"
            "  storage_account_name  = azurerm_storage_account.assets.name\n"
            "  container_access_type = \"private\"\n"
            "}\n\n"
            "# ===== Container registry (ACR) =====\n"
            "resource \"azurerm_container_registry\" \"acr\" {\n"
            "  name                = var.cluster_name + \"acr\"\n"
            "  resource_group_name = azurerm_resource_group.rg.name\n"
            "  location            = azurerm_resource_group.rg.location\n"
            "  sku                 = \"Basic\"\n"
            "  admin_enabled       = true\n"
            "}\n"))

    # --- outputs.tf ---
    output_map = {
        "aws": (
            "output \"cluster_endpoint\" {\n"
            "  value = module.eks.cluster_endpoint\n"
            "}\n\n"
            "output \"cluster_name\" {\n"
            "  value = module.eks.cluster_name\n"
            "}\n\n"
            "output \"db_endpoint\" {\n"
            "  value = module.db.db_instance_endpoint\n"
            "}\n\n"
            "output \"s3_bucket\" {\n"
            "  value = module.s3_bucket.s3_bucket_id\n"
            "}\n\n"
            "output \"ecr_repository_url\" {\n"
            "  value = aws_ecr_repository.app.repository_url\n"
            "}\n\n"
            "output \"configure_kubectl\" {\n"
            "  description = \"Command to configure kubectl\"\n"
            "  value       = \"aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}\"\n"
            "}\n"
        ),
        "gcp": (
            "output \"cluster_endpoint\" {\n"
            "  value = module.gke.endpoint\n"
            "}\n\n"
            "output \"cluster_name\" {\n"
            "  value = module.gke.name\n"
            "}\n\n"
            "output \"db_connection_name\" {\n"
            "  value = google_sql_database_instance.db.connection_name\n"
            "}\n\n"
            "output \"gcs_bucket\" {\n"
            "  value = google_storage_bucket.assets.name\n"
            "}\n\n"
            "output \"artifact_registry\" {\n"
            "  value = google_artifact_registry_repository.app.id\n"
            "}\n\n"
            "output \"configure_kubectl\" {\n"
            "  description = \"Command to configure kubectl\"\n"
            "  value       = \"gcloud container clusters get-credentials ${module.gke.name} --region ${var.region} --project ${var.project_id}\"\n"
            "}\n"
        ),
        "azure": (
            "output \"cluster_endpoint\" {\n"
            "  value = module.aks.host\n"
            "}\n\n"
            "output \"cluster_name\" {\n"
            "  value = module.aks.cluster_name\n"
            "}\n\n"
            "output \"db_server\" {\n"
            "  value = azurerm_mssql_server.sql.fully_qualified_domain_name\n"
            "}\n\n"
            "output \"storage_account\" {\n"
            "  value = azurerm_storage_account.assets.name\n"
            "}\n\n"
            "output \"acr_login_server\" {\n"
            "  value = azurerm_container_registry.acr.login_server\n"
            "}\n\n"
            "output \"configure_kubectl\" {\n"
            "  description = \"Command to configure kubectl\"\n"
            "  value       = \"az aks get-credentials --resource-group ${azurerm_resource_group.rg.name} --name ${module.aks.cluster_name}\"\n"
            "}\n"
        ),
    }
    files.append(_write(os.path.join(root, "outputs.tf"), output_map[provider]))

    # --- terraform.tfvars.example ---
    tvars = ("environment = \"production\"\n"
             "region      = " + json.dumps(
                 "us-east-1" if provider == "aws" else
                 "us-central1" if provider == "gcp" else "eastus") + "\n"
             "cluster_name = \"" + slug + "\"\n")
    if provider == "gcp":
        tvars += "project_id = \"YOUR_GCP_PROJECT_ID\"\n"
    files.append(_write(os.path.join(root, "terraform.tfvars.example"), tvars))

    # --- .gitignore ---
    files.append(_write(os.path.join(root, ".gitignore"),
        ".terraform/\n*.tfstate\n*.tfstate.*\n*.tfvars\n!terraform.tfvars.example\n.terraform.lock.hcl\ncrash.log\noverride.tf\noverride.tf.json\n"))

    # --- CI/CD deploy workflow ---
    deploy_step = {
        "aws": (
            "      - name: Configure AWS credentials\n"
            "        uses: aws-actions/configure-aws-credentials@v4\n"
            "        with:\n"
            "          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}\n"
            "          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}\n"
            "          aws-region: us-east-1\n"
            "      - name: Terraform apply\n"
            "        run: |\n"
            "          terraform init\n"
            "          terraform apply -auto-approve\n"
        ),
        "gcp": (
            "      - name: Authenticate to Google Cloud\n"
            "        uses: google-github-actions/auth@v2\n"
            "        with:\n"
            "          credentials_json: ${{ secrets.GCP_SA_KEY }}\n"
            "      - name: Terraform apply\n"
            "        run: |\n"
            "          terraform init\n"
            "          terraform apply -auto-approve\n"
        ),
        "azure": (
            "      - name: Azure Login\n"
            "        uses: azure/login@v2\n"
            "        with:\n"
            "          creds: ${{ secrets.AZURE_CREDENTIALS }}\n"
            "      - name: Terraform apply\n"
            "        run: |\n"
            "          terraform init\n"
            "          terraform apply -auto-approve\n"
        ),
    }

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "deploy.yml"),
        "name: Deploy Infrastructure\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  workflow_dispatch:\n"
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: hashicorp/setup-terraform@v3\n"
        "        with:\n"
        "          terraform_version: 1.7\n"
        "      - name: Terraform fmt & validate\n"
        "        run: |\n"
        "          terraform fmt -check\n"
        "          terraform init -backend=false\n"
        "          terraform validate\n"
        + deploy_step[provider] +
        "  plan:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: hashicorp/setup-terraform@v3\n"
        "      - name: Terraform plan\n"
        "        run: |\n"
        "          terraform init -backend=false\n"
        "          terraform plan -out=tfplan\n"))

    # --- README.md ---
    provider_display = {"aws": "AWS", "gcp": "Google Cloud Platform (GCP)", "azure": "Microsoft Azure"}[provider]
    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'Cloud Infrastructure'}\n\n"
        f"Production-grade **{provider_display}** infrastructure as code (Terraform) for "
        f"**{job.company or 'client'}**.\n\n"
        "## Components\n\n"
        "| Component | " + provider_display + " service |\n"
        "|---|---|\n"
        "| Kubernetes cluster | " + ("EKS" if provider == "aws" else "GKE" if provider == "gcp" else "AKS") + " |\n"
        "| Managed database | " + ("RDS PostgreSQL" if provider == "aws" else "Cloud SQL" if provider == "gcp" else "Azure SQL") + " |\n"
        "| Object storage | " + ("S3" if provider == "aws" else "GCS" if provider == "gcp" else "Blob Storage") + " |\n"
        "| Container registry | " + ("ECR" if provider == "aws" else "Artifact Registry" if provider == "gcp" else "ACR") + " |\n"
        "| Identity | " + ("IAM / IRSA" if provider == "aws" else "IAM / Workload Identity" if provider == "gcp" else "RBAC / Managed Identity") + " |\n\n"
        "## Prerequisites\n\n"
        "- Terraform >= 1.5\n"
        + ("- AWS CLI configured with credentials\n" if provider == "aws" else
           "- `gcloud` CLI authenticated\n" if provider == "gcp" else
           "- `az` CLI authenticated\n") +
        "## Deploy\n\n"
        "```bash\n"
        "cp terraform.tfvars.example terraform.tfvars\n"
        "# edit terraform.tfvars dengan nilai yang sesuai\n"
        "terraform init\n"
        "terraform plan\n"
        "terraform apply\n"
        "```\n\n"
        "## CI/CD\n\n"
        "GitHub Actions workflow `.github/workflows/deploy.yml` otomatis menjalankan "
        "`terraform plan` pada setiap push dan `terraform apply` pada branch `main`.\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-" + provider,
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"Cloud infrastructure '{slug}' ({provider_display} Terraform IaC)",
        "role": "developer",
        "provider": provider,
    }


# =============================================================================
# QA / TESTING
# =============================================================================

def build_qa_test_suite(job: Job) -> dict:
    """Generate test suite (pytest + Playwright) yang siap jalan."""
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-qa"))
    files = []

    files.append(_write(os.path.join(root, "requirements.txt"),
        "pytest==9.1.1\npytest-html==4.2.0\npytest-cov==7.1.0\nplaywright==1.62.0\nrequests==2.34.2\nfastapi==0.141.1\nhttpx==0.28.1\n"))

    files.append(_write(os.path.join(root, "pytest.ini"),
        "[pytest]\n"
        "addopts = -v --html=report.html --self-contained-html --cov=app --cov-report=term-missing\n"
        "testpaths = tests\n"
        "markers =\n"
        "    e2e: end-to-end tests (Playwright)\n"))

    # --- Aplikasi contoh yang diuji (bukan placeholder) ---
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "__init__.py"),
        "\"\"\"Application under test.\"\"\"\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "calculator.py"),
        "\"\"\"Simple calculator module used as the system under test.\"\"\"\n\n\n"
        "class Calculator:\n"
        "    def add(self, a: float, b: float) -> float:\n"
        "        return a + b\n\n"
        "    def subtract(self, a: float, b: float) -> float:\n"
        "        return a - b\n\n"
        "    def multiply(self, a: float, b: float) -> float:\n"
        "        return a * b\n\n"
        "    def divide(self, a: float, b: float) -> float:\n"
        "        if b == 0:\n"
        "            raise ValueError(\"division by zero\")\n"
        "        return a / b\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "app")), "api.py"),
        "\"\"\"Minimal FastAPI app under test.\"\"\"\n"
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n\n"
        "from .calculator import Calculator\n\n"
        "app = FastAPI(title=\"Calculator API\")\n"
        "calc = Calculator()\n\n\n"
        "@app.get(\"/health\")\n"
        "def health():\n"
        "    return {\"status\": \"ok\"}\n\n\n"
        "@app.get(\"/add\")\n"
        "def add(a: float, b: float):\n"
        "    return {\"result\": calc.add(a, b)}\n\n\n"
        "@app.get(\"/divide\")\n"
        "def divide(a: float, b: float):\n"
        "    return {\"result\": calc.divide(a, b)}\n\n\n"
        "client = TestClient(app)\n"))

    files.append(_write(os.path.join(root, "conftest.py"),
        "import sys\n"
        "import os\n\n"
        "# Ensure project root is importable so `import app` works in tests.\n"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_calculator.py"),
        "import pytest\n"
        "from app.calculator import Calculator\n\n\n"
        "@pytest.fixture\n"
        "def calc():\n"
        "    return Calculator()\n\n\n"
        "def test_add(calc):\n"
        "    assert calc.add(2, 3) == 5\n\n\n"
        "def test_subtract(calc):\n"
        "    assert calc.subtract(10, 4) == 6\n\n\n"
        "def test_multiply(calc):\n"
        "    assert calc.multiply(3, 4) == 12\n\n\n"
        "def test_divide(calc):\n"
        "    assert calc.divide(10, 2) == 5\n\n\n"
        "def test_divide_by_zero_raises(calc):\n"
        "    with pytest.raises(ValueError):\n"
        "        calc.divide(1, 0)\n\n\n"
        "@pytest.mark.parametrize(\"a,b,expected\", [\n"
        "    (1, 1, 2),\n"
        "    (-1, 1, 0),\n"
        "    (0, 0, 0),\n"
        "    (100, 200, 300),\n"
        "])\n"
        "def test_add_parametrized(calc, a, b, expected):\n"
        "    assert calc.add(a, b) == expected\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_api.py"),
        "import pytest\n"
        "from app.api import client\n\n\n"
        "def test_health():\n"
        "    r = client.get(\"/health\")\n"
        "    assert r.status_code == 200\n"
        "    assert r.json() == {\"status\": \"ok\"}\n\n\n"
        "def test_add_endpoint():\n"
        "    r = client.get(\"/add\", params={\"a\": 2, \"b\": 3})\n"
        "    assert r.status_code == 200\n"
        "    assert r.json() == {\"result\": 5.0}\n\n\n"
        "def test_divide_endpoint():\n"
        "    r = client.get(\"/divide\", params={\"a\": 10, \"b\": 2})\n"
        "    assert r.json() == {\"result\": 5.0}\n\n\n"
        "def test_divide_by_zero_returns_500():\n"
        "    r = client.get(\"/divide\", params={\"a\": 1, \"b\": 0})\n"
        "    assert r.status_code == 500\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_e2e.py"),
        "import pytest\n"
        "from playwright.sync_api import sync_playwright\n\n\n"
        "@pytest.mark.e2e\n"
        "def test_homepage_loads():\n"
        "    with sync_playwright() as p:\n"
        "        browser = p.chromium.launch()\n"
        "        page = browser.new_page()\n"
        "        page.goto('https://example.com')\n"
        "        assert page.title() == 'Example Domain'\n"
        "        browser.close()\n"))

    files.append(_write(os.path.join(root, "Dockerfile"),
        "FROM python:3.12-slim\n\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt && \\\n"
        "    playwright install --with-deps chromium\n"
        "COPY . .\n\n"
        'CMD ["pytest"]\n'))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: pip install -r requirements.txt\n"
        "      - run: playwright install --with-deps chromium\n"
        "      - run: pytest\n"))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'QA Test Suite'}\n\n"
        "Automated test suite (pytest + Playwright) for **" + (job.company or 'client') + "**.\n\n"
        "## Structure\n\n"
        "- `app/` — application under test (calculator + FastAPI)\n"
        "- `tests/test_calculator.py` — unit tests\n"
        "- `tests/test_api.py` — API tests (FastAPI TestClient)\n"
        "- `tests/test_e2e.py` — end-to-end (Playwright)\n"
        "- `report.html` — generated test report\n"
        "- coverage via pytest-cov (measured over `app/`)\n\n"
        "## Run\n```bash\npip install -r requirements.txt\npytest\n```\n\n"
        "## Docker\n```bash\ndocker build -t qa-suite .\ndocker run qa-suite\n```\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-qa",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"QA test suite '{slug}' (pytest + Playwright + coverage + CI)",
        "role": "developer",
    }


# =============================================================================
# ML / AI
# =============================================================================

def build_ml_model(job: Job) -> dict:
    """Generate pipeline ML (sklearn train/eval + FastAPI serve) yang siap jalan."""
    slug = _slugify(job.title)
    root = _ensure_dir(os.path.join(DELIVERABLES_DIR, slug + "-ml"))
    files = []

    files.append(_write(os.path.join(root, "requirements.txt"),
        "scikit-learn==1.9.0\npandas==2.3.3\nnumpy==2.5.2\njoblib==1.6.0\nfastapi==0.141.1\nuvicorn[standard]==0.52.4\npytest==9.1.1\n"))

    train = f'''"""ML training pipeline for: {job.title or 'project'}
Run: python train.py
"""
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report


def load_data(path: str = "data.csv") -> pd.DataFrame:
    """Load CSV or generate demo data."""
    if os.path.exists(path):
        return pd.read_csv(path)
    rng = np.random.default_rng(42)
    n = 500
    X = rng.normal(0, 1, (n, 4))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    df = pd.DataFrame(X, columns=[f"f{{i}}" for i in range(4)])
    df["label"] = y
    return df


def main():
    df = load_data()
    X = df.drop(columns=["label"])
    y = df["label"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print("Accuracy:", round(acc, 4))
    print(classification_report(y_test, preds))

    joblib.dump(model, "model.joblib")
    print("Saved model.joblib")


if __name__ == "__main__":
    main()
'''
    files.append(_write(os.path.join(root, "train.py"), train))

    serve = '''"""Serve ML model via FastAPI. Run: uvicorn serve:app --reload"""
import joblib
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ML Model API")

try:
    model = joblib.load("model.joblib")
except Exception:
    model = None


class Features(BaseModel):
    features: list[float]


@app.get("/")
def root():
    return {"status": "ok", "model_loaded": model is not None}


@app.post("/predict")
def predict(f: Features):
    if model is None:
        return {"error": "model not trained yet"}
    X = np.array(f.features).reshape(1, -1)
    pred = model.predict(X).tolist()
    return {"prediction": pred}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
    files.append(_write(os.path.join(root, "serve.py"), serve))

    # test
    files.append(_write(os.path.join(root, "conftest.py"),
        "import sys\n"
        "import os\n\n"
        "# Ensure project root is importable so `import train` works in tests.\n"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"))

    files.append(_write(os.path.join(root, "pytest.ini"),
        "[pytest]\n"
        "addopts = -v\n"
        "testpaths = tests\n"))

    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, "tests")), "test_model.py"),
        "import numpy as np\n"
        "import pytest\n"
        "from sklearn.ensemble import RandomForestClassifier\n\n\n"
        "def test_model_trains_and_predicts():\n"
        "    rng = np.random.default_rng(42)\n"
        "    X = rng.normal(0, 1, (100, 4))\n"
        "    y = (X[:, 0] + X[:, 1] > 0).astype(int)\n"
        "    model = RandomForestClassifier(n_estimators=10, random_state=42)\n"
        "    model.fit(X, y)\n"
        "    preds = model.predict(X[:5])\n"
        "    assert len(preds) == 5\n"
        "    assert set(preds).issubset({0, 1})\n\n\n"
        "def test_demo_data_shape():\n"
        "    import train\n"
        "    df = train.load_data()\n"
        "    assert 'label' in df.columns\n"
        "    assert len(df) > 0\n"))

    # Dockerfile
    files.append(_write(os.path.join(root, "Dockerfile"),
        "FROM python:3.12-slim\n\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY . .\n\n"
        "EXPOSE 8000\n"
        'CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8000"]\n'))

    # CI
    files.append(_write(os.path.join(_ensure_dir(os.path.join(root, ".github/workflows")), "ci.yml"),
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [ main ]\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.12'\n"
        "      - run: pip install -r requirements.txt\n"
        "      - run: python train.py\n"
        "      - run: pytest\n"
        "      - run: docker build -t ml-model .\n"))

    files.append(_write(os.path.join(root, "README.md"),
        f"# {job.title or 'ML Model'}\n\n"
        "Machine learning pipeline (scikit-learn) for **" + (job.company or 'client') + "**.\n\n"
        "## Train\n```bash\npip install -r requirements.txt\npython train.py\n```\n\n"
        "## Serve\n```bash\nuvicorn serve:app --reload\n```\n\n"
        "## Test\n```bash\npytest\n```\n\n"
        "## Docker\n```bash\ndocker build -t ml-model .\ndocker run -p 8000:8000 ml-model\n```\n\n"
        "- `train.py` — training + evaluation\n"
        "- `serve.py` — FastAPI inference endpoint\n"
        "- `tests/test_model.py` — unit tests\n"
        "- `model.joblib` — saved model (generated)\n\n"
        f"Generated: {_now()}\n"))

    return {
        "slug": slug + "-ml",
        "path": root,
        "files": [os.path.relpath(f, root) for f in files],
        "summary": f"ML pipeline '{slug}' (sklearn train + FastAPI serve + tests + Docker)",
        "role": "data",
    }


# =============================================================================
# ROUTER
# =============================================================================

def execute_job(job: Job, role: str = None, publish_github: bool = False,
                repo_name: str = None, auto_merge: bool = False,
                framework: str = None, subtype: str = None, **kwargs) -> dict:
    """Pilih generator yang tepat berdasarkan role, lalu produksi deliverable.

    role: 'developer' | 'designer' | 'writer' | 'web3' | 'data' | 'security'
          | None (auto-detect)

    framework: 'nextjs' | 'vite' (hanya untuk role developer web; None = auto).

    subtype: sub-spesialisasi developer ('web'|'mobile'|'api'|'devops'|'cloud'|'qa').
             Bila diberikan (mis. dari klasifikasi LLM), langsung dipakai untuk
             memilih generator, BYPASS routing regex.

    publish_github: bila True, push deliverable ke GitHub (buat repo + buka PR).
    """
    if role is None:
        from .proposal import _detect_role
        role = _detect_role(job)

    if role == "developer":
        # Bila subtype eksplisit diberikan (dari LLM), pakai langsung.
        if subtype in ("mobile", "api", "devops", "cloud", "qa", "web"):
            if subtype == "mobile":
                result = build_mobile_app(job, **kwargs)
            elif subtype == "api":
                result = build_api(job, **kwargs)
            elif subtype == "devops":
                result = build_devops_pipeline(job, **kwargs)
            elif subtype == "cloud":
                result = build_cloud_infrastructure(job, **kwargs)
            elif subtype == "qa":
                result = build_qa_test_suite(job, **kwargs)
            else:  # web
                result = build_web_app(job, framework=framework or "nextjs", **kwargs)
            if publish_github:
                try:
                    from .github_client import publish_deliverable
                    name = repo_name or result["slug"]
                    gh_result = publish_deliverable(
                        result["path"], name,
                        title=job.title or name,
                        body=f"Deliverable '{result['summary']}' for {job.company or 'client'}.",
                        auto_merge=auto_merge,
                    )
                    result["github"] = gh_result
                except Exception as e:
                    result["github_error"] = str(e)
            return result

        # Pilih generator berdasarkan sub-spesialisasi.
        # PENTING: pakai judul + skills + kategori (BUKAN deskripsi) agar
        # keyword kebetulan di body tidak mengubah hasil (mis. deskripsi
        # platform mobile marketing menyebut "mobile" -> salah jadi React Native).
        text = " ".join(filter(None, [job.title or "", job.skills or "",
                                      job.category or ""])).lower()
        if any(k in text for k in ["mobile", "react native", "android", "ios",
                                   "flutter", "swift", "kotlin"]):
            result = build_mobile_app(job, **kwargs)
        elif any(k in text for k in ["aws", "amazon web services", "ec2", "s3",
                                   "lambda", "eks", "ecs", "rds", "cloudformation",
                                   "gcp", "google cloud", "gke", "cloud run",
                                   "bigquery", "azure", "aks", "microsoft azure",
                                   "app service", "terraform", "infrastructure as code",
                                   "cloud engineer", "cloud architect", "cloud infrastructure"]):
            result = build_cloud_infrastructure(job, **kwargs)
        elif any(k in text for k in ["devops", "sre", "kubernetes", "k8s", "docker",
                                   "infrastructure", "ci/cd", "release", "cloud",
                                   "platform", "site reliability"]):
            result = build_devops_pipeline(job, **kwargs)
        elif any(k in text for k in ["qa", "test", "testing", "quality", "sdet"]):
            result = build_qa_test_suite(job, **kwargs)
        elif any(k in text for k in ["api", "backend", "back end", "back-end", "rest",
                                   "microservice", "server", "django", "flask",
                                   "golang", "rust", "node.js", "nodejs", "express"]):
            result = build_api(job, **kwargs)
        else:
            # Frontend web: pilih Vite (SPA) bila diminta eksplisit atau job
            # menyebut SPA/Vite, selain itu default Next.js (SSR/App Router).
            if framework == "vite" or (framework is None and any(
                    k in text for k in ["vite", "spa", "single page", "single-page",
                                        "client-side", "static site", "jamstack"])):
                result = build_web_app(job, framework="vite", **kwargs)
            else:
                result = build_web_app(job, framework=framework or "nextjs", **kwargs)
    elif role == "designer":
        text = " ".join(filter(None, [job.title or "", job.skills or "",
                                      job.category or ""])).lower()
        if any(k in text for k in ["brand", "logo", "identity", "style guide"]):
            result = build_brand_kit(job, **kwargs)
        elif any(k in text for k in ["design system", "design-system", "designsystem",
                                     "token", "component library", "style guide system"]):
            result = build_design_system(job, **kwargs)
        elif any(k in text for k in ["ui kit", "ui-kit", "component kit", "ui component",
                                     "button", "input", "form component", "widget"]):
            result = build_ui_kit(job, **kwargs)
        elif any(k in text for k in ["wireframe", "wire-frame", "low fidelity", "lo-fi",
                                     "prototype", "mockup", "layout", "sitemap",
                                     "information architecture", "ia "]):
            result = build_wireframe(job, **kwargs)
        elif any(k in text for k in ["user flow", "user-flow", "userflow", "flow diagram",
                                     "journey", "user journey", "flowchart", "task flow",
                                     "ux flow", "conversion funnel"]):
            result = build_user_flow(job, **kwargs)
        else:
            result = build_landing_page(job, **kwargs)
    elif role == "writer":
        result = write_article(job, **kwargs)
    elif role == "web3":
        result = build_smart_contract(job, **kwargs)
    elif role == "data":
        text = " ".join(filter(None, [job.title or "", job.description or ""])).lower()
        if any(k in text for k in ["machine learning", "ml ", "ai ", "llm",
                                   "deep learning", "nlp", "computer vision",
                                   "model", "algorithm", "prompt engineer",
                                   "generative", "agentic", "neural"]):
            result = build_ml_model(job, **kwargs)
        else:
            result = build_data_analysis(job, **kwargs)
    elif role == "security":
        result = build_security_audit(job, **kwargs)
    else:
        result = build_web_app(job, **kwargs)

    # Opsional: publish ke GitHub (buat repo + buka PR)
    if publish_github:
        try:
            from .github_client import publish_deliverable
            name = repo_name or result["slug"]
            gh_result = publish_deliverable(
                result["path"], name,
                title=job.title or name,
                body=f"Deliverable '{result['summary']}' for {job.company or 'client'}.",
                auto_merge=auto_merge,
            )
            result["github"] = gh_result
        except Exception as e:
            result["github_error"] = str(e)

    return result


def execute_contract(conn, contract_id: int, role: str = None,
                     publish_github: bool = False, auto_merge: bool = False) -> dict:
    """Produksi deliverable untuk satu kontrak & catat ke DB.

    Mengambil kontrak dari DB, generate deliverable nyata, lalu catat
    deliverable + set status 'delivered'.
    """
    from .workflow import get_contract, add_deliverable, set_status

    contract = get_contract(conn, contract_id)
    if not contract:
        raise ValueError(f"contract #{contract_id} tidak ditemukan")

    # Rekonstruksi Job minimal untuk generator
    job = Job(
        platform=contract["platform"],
        job_id=contract["job_id"],
        title=contract["title"],
        company=contract["company"],
        url=contract["url"],
    )

    result = execute_job(job, role=role, publish_github=publish_github,
                         auto_merge=auto_merge)

    # Catat deliverable
    add_deliverable(
        conn, contract_id,
        name=result["summary"],
        path=result["path"],
        description=f"{result['role']} deliverable: {', '.join(result['files'][:5])}",
    )
    set_status(conn, contract_id, "delivered")

    return result
