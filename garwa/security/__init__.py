"""
security package
Orkestrasi security scanner lokal (semgrep/osv/pip-audit/dep-scan/
gitleaks/trivy/zap) -- dipecah dari security.py (satu file besar) jadi
beberapa modul kecil per tanggung jawab. Diimpor sebagai `security`
(lihat `garwa/security/__init__.py`) supaya `import security as
security_mod; security_mod.security_scan(...)` di tools.py tetap
bekerja tanpa berubah.
"""
from .findings import Finding
from .orchestrator import security_scan, SCANNER_REGISTRY, MODE_SCANNERS
from . import _shared as shared

DEFAULT_TIMEOUT = shared.DEFAULT_TIMEOUT
MAX_TIMEOUT = shared.MAX_TIMEOUT
MAX_FINDINGS = shared.MAX_FINDINGS
