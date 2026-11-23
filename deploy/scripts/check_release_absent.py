"""Fail closed unless the GitHub Release for a tag is confirmed absent.

Only HTTP 404 is evidence that the Release does not exist.  200 means the
Release already exists and must stop the workflow before any GHCR push.
401/403/429/5xx, malformed responses, timeouts and network errors are all
"unknown" and must also stop: treating an API failure as "not found" is a
release-identity bypass.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from release_common import ReleaseError

API_ROOT = "https://api.github.com"


def classify_http_status(status: int) -> str:
    """Map a GitHub Releases API status to exists / absent / unknown."""
    if status == 200:
        return "exists"
    if status == 404:
        return "absent"
    return "unknown"


def query_release_status(
    repo: str,
    tag: str,
    token: str,
    opener=urlopen,
    timeout: int = 20,
    api_root: str = API_ROOT,
) -> int:
    """Return the HTTP status for GET /repos/{repo}/releases/tags/{tag}."""
    if not repo.strip():
        raise ReleaseError("GitHub repository 不能为空")
    if not tag.strip():
        raise ReleaseError("Release tag 不能为空")
    if not token.strip():
        raise ReleaseError("GITHUB_TOKEN/GH_TOKEN 不能为空")

    url = f"{api_root.rstrip('/')}/repos/{repo}/releases/tags/{quote(tag, safe='')}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "geo-system-release-check",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            if isinstance(status, bool) or not isinstance(status, int):
                raise ReleaseError(f"GitHub Release 查询返回非法状态：{status!r}")
            return status
    except HTTPError as exc:
        return int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        raise ReleaseError(f"查询 GitHub Release 失败：{exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="确认 GitHub Release 不存在；只有 HTTP 404 可以继续")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/repo")
    parser.add_argument("--tag", default=os.environ.get("TAG", ""), help="release tag")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    try:
        status = query_release_status(args.repo, args.tag, token)
    except ReleaseError as exc:
        print(f"FAIL 无法确认 GitHub Release 是否存在：{exc}")
        return 1

    decision = classify_http_status(status)
    if decision == "exists":
        print(f"FAIL Release {args.tag} 已存在，拒绝重复发布")
        return 1
    if decision == "absent":
        print(f"OK Release {args.tag} 不存在（HTTP 404），可以继续")
        return 0

    print(f"FAIL 查询 GitHub Release 返回 HTTP {status}；无法确认不存在，失败关闭")
    return 1


if __name__ == "__main__":
    sys.exit(main())
