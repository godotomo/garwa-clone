"""jobbot/github_client.py - Klien GitHub REST API lengkap untuk jobbot.

Mendukung operasi penuh (bukan hanya commit & push): membuat repo, branch,
menulis file, commit, push, membuka Pull Request, review, merge, dan komentar.

Auth: personal access token (fine-grained/classic) via env:
  - GITHUB_TOKEN  (atau JOB_GITHUB_TOKEN)
  - GITHUB_USER   (atau JOB_GITHUB_USER)  -- username akun GitHub

Semua operasi pakai REST API v3 (https://api.github.com) dengan token Bearer.
Tidak bergantung pada `gh` CLI atau GitPython -- murni `requests` + `git`
subprocess untuk operasi lokal (init/add/commit/push).

Contoh alur end-to-end (membuat PR dari deliverable):
    gh = GitHubClient()
    repo = gh.create_repo("my-deliverable", private=True)
    gh.write_file(repo, "README.md", "# Hello", branch="main")
    pr = gh.create_pull_request(repo, "feature/x", "main", "Add deliverable", "body")
    gh.add_review(pr["number"], "APPROVE", "LGTM")
    gh.merge_pull_request(pr["number"], method="squash")
"""
import base64
import os
import subprocess
from typing import Optional

import requests

from . import db


class GitHubError(Exception):
    """Error dari GitHub API / operasi git lokal."""


class GitHubClient:
    """Wrapper GitHub REST API + operasi git lokal."""

    API = "https://api.github.com"

    def __init__(self, token: str = None, user: str = None):
        self.token = token or db.get_env("GITHUB_TOKEN")
        self.user = user or db.get_env("GITHUB_USER") or db.get_env("GITHUB_USERNAME")
        if not self.token:
            raise GitHubError(
                "GITHUB_TOKEN belum diset. Set env GITHUB_TOKEN (atau JOB_GITHUB_TOKEN) "
                "di .env dengan personal access token GitHub."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "jobbot/1.0",
        })

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.API}{path}"
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub {method} {path} -> {resp.status_code}: "
                f"{resp.text[:500]}"
            )
        if resp.status_code == 204:
            return {}
        return resp.json()

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    def _put(self, path: str, **kwargs) -> dict:
        return self._request("PUT", path, **kwargs)

    def _patch(self, path: str, **kwargs) -> dict:
        return self._request("PATCH", path, **kwargs)

    def _delete(self, path: str, **kwargs) -> dict:
        return self._request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------
    # User / auth
    # ------------------------------------------------------------------
    def whoami(self) -> dict:
        """Return user yang terautentikasi (login, name, email)."""
        return self._get("/user")

    def resolve_user(self) -> str:
        """Pastikan username tersedia (dari argumen atau /user)."""
        if self.user:
            return self.user
        u = self.whoami()
        self.user = u.get("login")
        if not self.user:
            raise GitHubError("Tidak bisa menentukan username GitHub.")
        return self.user

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------
    def list_repos(self, per_page: int = 30) -> list[dict]:
        return self._get("/user/repos", params={"per_page": per_page,
                                                "sort": "updated"})

    def get_repo(self, repo: str) -> dict:
        """repo dalam bentuk 'owner/name'."""
        return self._get(f"/repos/{repo}")

    def repo_exists(self, repo: str) -> bool:
        try:
            self.get_repo(repo)
            return True
        except GitHubError:
            return False

    def create_repo(self, name: str, private: bool = True,
                    description: str = "", auto_init: bool = True) -> dict:
        """Buat repo baru di akun user. Return dict repo."""
        payload = {
            "name": name,
            "private": private,
            "description": description,
            "auto_init": auto_init,
            "default_branch": "main",
        }
        return self._post("/user/repos", json=payload)

    def delete_repo(self, repo: str) -> dict:
        return self._delete(f"/repos/{repo}")

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------
    def list_branches(self, repo: str) -> list[dict]:
        return self._get(f"/repos/{repo}/branches")

    def get_branch(self, repo: str, branch: str) -> dict:
        return self._get(f"/repos/{repo}/branches/{branch}")

    def create_branch(self, repo: str, branch: str, from_branch: str = "main") -> dict:
        """Buat branch baru dari branch lain (ambil SHA lalu create ref)."""
        base = self.get_branch(repo, from_branch)
        sha = base["commit"]["sha"]
        return self._post(
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def delete_branch(self, repo: str, branch: str) -> dict:
        return self._delete(f"/repos/{repo}/git/refs/heads/{branch}")

    # ------------------------------------------------------------------
    # Files / contents
    # ------------------------------------------------------------------
    def read_file(self, repo: str, path: str, branch: str = "main") -> str:
        """Baca isi file (decode base64)."""
        data = self._get(
            f"/repos/{repo}/contents/{path}",
            params={"ref": branch},
        )
        content = data.get("content", "")
        return base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")

    def write_file(self, repo: str, path: str, content: str,
                   message: str = "Add file", branch: str = "main",
                   sha: str = None) -> dict:
        """Buat/update satu file via contents API. Return commit dict."""
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        return self._put(f"/repos/{repo}/contents/{path}", json=payload)

    def delete_file(self, repo: str, path: str, message: str,
                    branch: str = "main", sha: str = None) -> dict:
        if sha is None:
            data = self._get(f"/repos/{repo}/contents/{path}", params={"ref": branch})
            sha = data["sha"]
        return self._delete(
            f"/repos/{repo}/contents/{path}",
            json={"message": message, "sha": sha, "branch": branch},
        )

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------
    def list_commits(self, repo: str, branch: str = "main", per_page: int = 30) -> list[dict]:
        return self._get(f"/repos/{repo}/commits",
                         params={"sha": branch, "per_page": per_page})

    def get_commit(self, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{repo}/commits/{sha}")

    def compare(self, repo: str, base: str, head: str) -> dict:
        return self._get(f"/repos/{repo}/compare/{base}...{head}")

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------
    def list_pull_requests(self, repo: str, state: str = "open") -> list[dict]:
        return self._get(f"/repos/{repo}/pulls", params={"state": state})

    def get_pull_request(self, repo: str, number: int) -> dict:
        return self._get(f"/repos/{repo}/pulls/{number}")

    def create_pull_request(self, repo: str, head: str, base: str,
                            title: str, body: str = "", draft: bool = False) -> dict:
        """Buka PR dari branch `head` ke `base`."""
        return self._post(
            f"/repos/{repo}/pulls",
            json={"title": title, "head": head, "base": base,
                  "body": body, "draft": draft},
        )

    def update_pull_request(self, repo: str, number: int, **fields) -> dict:
        return self._patch(f"/repos/{repo}/pulls/{number}", json=fields)

    def close_pull_request(self, repo: str, number: int) -> dict:
        return self.update_pull_request(repo, number, state="closed")

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------
    def list_reviews(self, repo: str, number: int) -> list[dict]:
        return self._get(f"/repos/{repo}/pulls/{number}/reviews")

    def add_review(self, repo: str, number: int, event: str,
                   body: str = "", commit_id: str = None) -> dict:
        """event: APPROVE | REQUEST_CHANGES | COMMENT."""
        payload = {"event": event, "body": body}
        if commit_id:
            payload["commit_id"] = commit_id
        return self._post(f"/repos/{repo}/pulls/{number}/reviews", json=payload)

    def submit_review(self, repo: str, number: int, review_id: int,
                      event: str, body: str = "") -> dict:
        return self._post(
            f"/repos/{repo}/pulls/{number}/reviews/{review_id}/events",
            json={"event": event, "body": body},
        )

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def list_comments(self, repo: str, number: int) -> list[dict]:
        return self._get(f"/repos/{repo}/issues/{number}/comments")

    def add_comment(self, repo: str, number: int, body: str) -> dict:
        return self._post(f"/repos/{repo}/issues/{number}/comments",
                          json={"body": body})

    def add_review_comment(self, repo: str, number: int, body: str,
                           path: str, line: int, commit_id: str) -> dict:
        """Komentar inline pada baris file tertentu di PR."""
        return self._post(
            f"/repos/{repo}/pulls/{number}/comments",
            json={"body": body, "path": path, "line": line,
                  "commit_id": commit_id},
        )

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------
    def merge_pull_request(self, repo: str, number: int,
                           method: str = "squash",
                           commit_title: str = None) -> dict:
        """Merge PR. method: merge | squash | rebase."""
        payload = {"merge_method": method}
        if commit_title:
            payload["commit_title"] = commit_title
        return self._put(f"/repos/{repo}/pulls/{number}/merge", json=payload)

    def check_mergeable(self, repo: str, number: int) -> bool:
        pr = self.get_pull_request(repo, number)
        return pr.get("mergeable", False) is True

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------
    def list_issues(self, repo: str, state: str = "open") -> list[dict]:
        return self._get(f"/repos/{repo}/issues", params={"state": state})

    def create_issue(self, repo: str, title: str, body: str = "",
                     labels: list[str] = None) -> dict:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._post(f"/repos/{repo}/issues", json=payload)

    # ------------------------------------------------------------------
    # GitHub Actions (workflows, runs, jobs, logs, dispatch)
    # ------------------------------------------------------------------
    def list_workflows(self, repo: str) -> dict:
        """List semua workflows (returns {total_count, workflows})."""
        return self._get(f"/repos/{repo}/actions/workflows")

    def get_workflow(self, repo: str, workflow_id) -> dict:
        """workflow_id: nama file (mis. 'ci.yml') atau ID numerik."""
        return self._get(f"/repos/{repo}/actions/workflows/{workflow_id}")

    def dispatch_workflow(self, repo: str, workflow_id, ref: str = "main",
                          inputs: dict = None) -> dict:
        """Trigger workflow_dispatch event. Return {} bila sukses (204)."""
        payload = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        return self._post(f"/repos/{repo}/actions/workflows/{workflow_id}/dispatches",
                          json=payload)

    def list_workflow_runs(self, repo: str, workflow_id=None,
                           status: str = None, branch: str = None,
                           per_page: int = 30) -> dict:
        """List workflow runs. workflow_id opsional (semua bila None)."""
        if workflow_id is not None:
            path = f"/repos/{repo}/actions/workflows/{workflow_id}/runs"
        else:
            path = f"/repos/{repo}/actions/runs"
        params = {"per_page": per_page}
        if status:
            params["status"] = status
        if branch:
            params["branch"] = branch
        return self._get(path, params=params)

    def get_workflow_run(self, repo: str, run_id: int) -> dict:
        return self._get(f"/repos/{repo}/actions/runs/{run_id}")

    def rerun_workflow(self, repo: str, run_id: int) -> dict:
        return self._post(f"/repos/{repo}/actions/runs/{run_id}/rerun")

    def cancel_workflow_run(self, repo: str, run_id: int) -> dict:
        return self._post(f"/repos/{repo}/actions/runs/{run_id}/cancel")

    def list_jobs_for_run(self, repo: str, run_id: int) -> dict:
        return self._get(f"/repos/{repo}/actions/runs/{run_id}/jobs")

    def get_job_logs(self, repo: str, job_id: int) -> str:
        """Download log satu job (return teks log)."""
        url = f"{self.API}/repos/{repo}/actions/jobs/{job_id}/logs"
        resp = self.session.get(url, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub get job logs -> {resp.status_code}: {resp.text[:300]}")
        return resp.text

    def download_workflow_logs(self, repo: str, run_id: int) -> str:
        """Download log seluruh run (zip, return bytes sebagai latin-1 str)."""
        url = f"{self.API}/repos/{repo}/actions/runs/{run_id}/logs"
        resp = self.session.get(url, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub download logs -> {resp.status_code}: {resp.text[:300]}")
        return resp.text

    # ------------------------------------------------------------------
    # Secrets (Actions / Dependabot) — encrypted via libsodium public key
    # ------------------------------------------------------------------
    def get_public_key(self, repo: str) -> dict:
        """Ambil public key repo untuk encrypt secret. Return {key_id, key}."""
        return self._get(f"/repos/{repo}/actions/secrets/public-key")

    def _encrypt_secret(self, public_key: str, value: str) -> str:
        """Encrypt secret pakai libsodium sealed box (base64)."""
        try:
            from nacl import encoding, public
        except ImportError:
            raise GitHubError(
                "pynacl belum terinstall. Jalankan: pip install pynacl "
                "untuk membuat/mengupdate secret."
            )
        pub = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed = public.SealedBox(pub)
        encrypted = sealed.encrypt(value.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")

    def list_secrets(self, repo: str) -> dict:
        return self._get(f"/repos/{repo}/actions/secrets")

    def get_secret(self, repo: str, name: str) -> dict:
        return self._get(f"/repos/{repo}/actions/secrets/{name}")

    def create_secret(self, repo: str, name: str, value: str) -> dict:
        """Buat/update secret (terenkripsi). Return {} bila sukses."""
        pub = self.get_public_key(repo)
        encrypted = self._encrypt_secret(pub["key"], value)
        return self._put(
            f"/repos/{repo}/actions/secrets/{name}",
            json={"encrypted_value": encrypted, "key_id": pub["key_id"]},
        )

    def delete_secret(self, repo: str, name: str) -> dict:
        return self._delete(f"/repos/{repo}/actions/secrets/{name}")

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------
    def list_releases(self, repo: str, per_page: int = 30) -> list[dict]:
        return self._get(f"/repos/{repo}/releases", params={"per_page": per_page})

    def get_release(self, repo: str, release_id: int) -> dict:
        return self._get(f"/repos/{repo}/releases/{release_id}")

    def get_latest_release(self, repo: str) -> dict:
        return self._get(f"/repos/{repo}/releases/latest")

    def create_release(self, repo: str, tag_name: str, name: str = None,
                       body: str = "", draft: bool = False,
                       prerelease: bool = False,
                       target_commitish: str = "main") -> dict:
        """Buat release (tag harus sudah ada atau auto-create via target)."""
        payload = {
            "tag_name": tag_name,
            "name": name or tag_name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
            "target_commitish": target_commitish,
        }
        return self._post(f"/repos/{repo}/releases", json=payload)

    def delete_release(self, repo: str, release_id: int) -> dict:
        return self._delete(f"/repos/{repo}/releases/{release_id}")

    def upload_release_asset(self, repo: str, release_id: int, file_path: str,
                             name: str = None, content_type: str = None) -> dict:
        """Upload file sebagai asset release. Return dict asset."""
        import mimetypes
        name = name or os.path.basename(file_path)
        content_type = content_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        url = (f"https://uploads.github.com/repos/{repo}/releases/"
               f"{release_id}/assets?name={name}")
        with open(file_path, "rb") as f:
            data = f.read()
        resp = self.session.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": content_type,
            },
            data=data,
        )
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub upload asset -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # ------------------------------------------------------------------
    # Deployments & environments
    # ------------------------------------------------------------------
    def list_deployments(self, repo: str, environment: str = None) -> list[dict]:
        params = {}
        if environment:
            params["environment"] = environment
        return self._get(f"/repos/{repo}/deployments", params=params)

    def create_deployment(self, repo: str, ref: str, environment: str = "production",
                          auto_merge: bool = True, description: str = "",
                          required_contexts: list[str] = None) -> dict:
        payload = {
            "ref": ref,
            "environment": environment,
            "auto_merge": auto_merge,
            "description": description,
        }
        if required_contexts:
            payload["required_contexts"] = required_contexts
        return self._post(f"/repos/{repo}/deployments", json=payload)

    def create_deployment_status(self, repo: str, deployment_id: int,
                                 state: str, environment_url: str = "",
                                 description: str = "") -> dict:
        """state: error | failure | inactive | in_progress | queued | success."""
        payload = {"state": state, "description": description}
        if environment_url:
            payload["environment_url"] = environment_url
        return self._post(
            f"/repos/{repo}/deployments/{deployment_id}/statuses", json=payload)

    def list_environments(self, repo: str) -> dict:
        return self._get(f"/repos/{repo}/environments")

    # ------------------------------------------------------------------
    # Commit status & check runs (CI feedback)
    # ------------------------------------------------------------------
    def create_commit_status(self, repo: str, sha: str, state: str,
                             context: str = "jobbot/ci", description: str = "",
                             target_url: str = "") -> dict:
        """state: error | failure | pending | success."""
        payload = {"state": state, "context": context, "description": description}
        if target_url:
            payload["target_url"] = target_url
        return self._post(f"/repos/{repo}/statuses/{sha}", json=payload)

    def list_commit_statuses(self, repo: str, sha: str) -> list[dict]:
        return self._get(f"/repos/{repo}/commits/{sha}/statuses")

    def get_combined_status(self, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{repo}/commits/{sha}/status")

    def list_check_runs(self, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{repo}/commits/{sha}/check-runs")

    # ------------------------------------------------------------------
    # Tags & refs (untuk release)
    # ------------------------------------------------------------------
    def create_tag(self, repo: str, tag: str, sha: str, message: str = "") -> dict:
        """Buat annotated/lightweight tag object lalu ref."""
        tag_obj = self._post(
            f"/repos/{repo}/git/tags",
            json={"tag": tag, "message": message or tag,
                  "object": sha, "type": "commit"},
        )
        self._post(f"/repos/{repo}/git/refs",
                   json={"ref": f"refs/tags/{tag}", "sha": tag_obj["sha"]})
        return tag_obj

    def list_tags(self, repo: str) -> list[dict]:
        return self._get(f"/repos/{repo}/tags")

    # ------------------------------------------------------------------
    # Operasi git lokal (init/add/commit/push) via subprocess
    # ------------------------------------------------------------------
    def git(self, *args: str, cwd: str = None, check: bool = True) -> str:
        """Jalankan perintah git. Return stdout ter-trim."""
        cmd = ["git", *args]
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                               timeout=120)
        except subprocess.TimeoutExpired as e:
            raise GitHubError(f"git {' '.join(args)} timeout: {e}")
        if check and r.returncode != 0:
            raise GitHubError(
                f"git {' '.join(args)} gagal (exit {r.returncode}): {r.stderr.strip()}"
            )
        return r.stdout.strip()

    def ensure_git_config(self, name: str = None, email: str = None) -> None:
        """Pastikan git user.name & user.email terkonfigurasi (global)."""
        name = name or db.get_env("GIT_USER_NAME") or db.get_env("GITHUB_USER")
        email = email or db.get_env("GIT_USER_EMAIL")
        if not name or not email:
            raise GitHubError(
                "GIT_USER_NAME dan GIT_USER_EMAIL (atau GITHUB_USER) wajib diset "
                "untuk commit. Set di .env."
            )
        self.git("config", "--global", "user.name", name)
        self.git("config", "--global", "user.email", email)

    def init_and_push(self, local_dir: str, repo: str, branch: str = "main",
                      commit_message: str = "Initial commit",
                      remote_name: str = "origin") -> dict:
        """Init repo lokal, commit semua file, push ke remote.

        Return dict {repo, branch, commit_sha, remote_url}.
        """
        self.git("init", "-b", branch, cwd=local_dir)
        self.git("add", "-A", cwd=local_dir)
        # commit (mungkin belum ada perubahan -> skip)
        try:
            self.git("commit", "-m", commit_message, cwd=local_dir)
        except GitHubError:
            pass  # nothing to commit
        remote_url = f"https://{self.token}@github.com/{repo}.git"
        self.git("remote", "remove", remote_name, cwd=local_dir, check=False)
        self.git("remote", "add", remote_name, remote_url, cwd=local_dir)
        self.git("push", "-u", remote_name, branch, cwd=local_dir)
        sha = self.git("rev-parse", "HEAD", cwd=local_dir)
        return {"repo": repo, "branch": branch, "commit_sha": sha,
                "remote_url": f"https://github.com/{repo}"}

    def push_branch(self, local_dir: str, repo: str, branch: str,
                    commit_message: str = "Update") -> dict:
        """Commit & push branch baru (untuk PR)."""
        self.git("checkout", "-b", branch, cwd=local_dir, check=False)
        self.git("add", "-A", cwd=local_dir)
        try:
            self.git("commit", "-m", commit_message, cwd=local_dir)
        except GitHubError:
            pass
        remote_url = f"https://{self.token}@github.com/{repo}.git"
        self.git("remote", "remove", "origin", cwd=local_dir, check=False)
        self.git("remote", "add", "origin", remote_url, cwd=local_dir)
        self.git("push", "-u", "origin", branch, cwd=local_dir)
        sha = self.git("rev-parse", "HEAD", cwd=local_dir)
        return {"repo": repo, "branch": branch, "commit_sha": sha}


def publish_deliverable(local_dir: str, repo_name: str, title: str,
                        body: str = "", private: bool = False,
                        base_branch: str = "main",
                        feature_branch: str = "deliverable",
                        auto_merge: bool = False) -> dict:
    """Alur end-to-end: buat repo -> push deliverable -> buka PR -> (opsional) merge.

    Return dict berisi repo, PR number, PR url, dan status merge.
    """
    gh = GitHubClient()
    gh.ensure_git_config()

    # 1. Buat repo (kalau belum ada)
    if gh.repo_exists(f"{gh.resolve_user()}/{repo_name}"):
        repo = gh.get_repo(f"{gh.resolve_user()}/{repo_name}")
    else:
        repo = gh.create_repo(repo_name, private=private,
                              description=title, auto_init=True)
    full_repo = repo["full_name"]

    # 2. Push deliverable ke feature branch
    gh.push_branch(local_dir, full_repo, feature_branch,
                   commit_message=f"Add deliverable: {title}")

    # 3. Buka PR
    pr = gh.create_pull_request(full_repo, feature_branch, base_branch,
                                title=title, body=body)

    result = {
        "repo": full_repo,
        "pr_number": pr["number"],
        "pr_url": pr["html_url"],
        "merged": False,
    }

    # 4. Opsional: review + merge otomatis
    if auto_merge:
        gh.add_review(full_repo, pr["number"], "APPROVE",
                      body="Automated review: deliverable looks good.")
        try:
            gh.merge_pull_request(full_repo, pr["number"], method="squash")
            result["merged"] = True
        except GitHubError as e:
            result["merge_error"] = str(e)

    return result
