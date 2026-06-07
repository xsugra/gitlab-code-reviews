import logging

import httpx

from . import settings

log = logging.getLogger(__name__)


class GitLabClient:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = url or settings.get("GITLAB_URL")
        self.base = self.url.rstrip("/") + "/api/v4"
        self.headers = {"PRIVATE-TOKEN": token or settings.get("GITLAB_TOKEN")}
        self._client = httpx.AsyncClient(headers=self.headers, timeout=60)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base}{path}"
        log.debug("%s %s", method.upper(), url)
        try:
            r = await self._client.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except httpx.ConnectError:
            log.error("Cannot connect to GitLab at %s — is it reachable?", self.url)
            raise
        except httpx.HTTPStatusError as e:
            log.error("GitLab HTTP %s on %s %s: %s",
                      e.response.status_code, method.upper(), path, e.response.text[:300])
            raise

    # ── Merge Request ────────────────────────────────────────────

    async def get_mr(self, project_id: int, mr_iid: int) -> dict:
        r = await self._request("GET", f"/projects/{project_id}/merge_requests/{mr_iid}")
        return r.json()

    async def get_diffs(self, project_id: int, mr_iid: int) -> list[dict]:
        diffs: list[dict] = []
        page = 1
        per_page = 50
        while True:
            r = await self._request(
                "GET", f"/projects/{project_id}/merge_requests/{mr_iid}/diffs",
                params={"page": page, "per_page": per_page}, timeout=120,
            )
            batch = r.json()
            if not batch:
                break
            diffs.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        log.debug("Fetched %d diff entries across %d page(s)", len(diffs), page)
        return diffs

    async def post_note(self, project_id: int, mr_iid: int, body: str) -> dict:
        r = await self._request(
            "POST", f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        return r.json()

    async def update_mr(self, project_id: int, mr_iid: int, **fields) -> dict:
        r = await self._request("PUT", f"/projects/{project_id}/merge_requests/{mr_iid}", json=fields)
        return r.json()

    # ── Push events ──────────────────────────────────────────────

    async def get_commit_diff(self, project_id: int, sha: str) -> list[dict]:
        r = await self._request("GET", f"/projects/{project_id}/repository/commits/{sha}/diff", timeout=120)
        return r.json()

    async def post_commit_comment(self, project_id: int, sha: str, body: str) -> dict:
        r = await self._request(
            "POST", f"/projects/{project_id}/repository/commits/{sha}/comments",
            json={"note": body},
        )
        return r.json()

    # ── Pipeline events ──────────────────────────────────────────

    async def get_pipeline_jobs(self, project_id: int, pipeline_id: int) -> list[dict]:
        r = await self._request(
            "GET", f"/projects/{project_id}/pipelines/{pipeline_id}/jobs",
            params={"per_page": 100},
        )
        return r.json()

    async def get_job_log(self, project_id: int, job_id: int, tail_chars: int = 20000) -> str:
        r = await self._request("GET", f"/projects/{project_id}/jobs/{job_id}/trace")
        text = r.text
        if len(text) > tail_chars:
            text = text[-tail_chars:]
        return text

    # ── Issue triage ─────────────────────────────────────────────

    async def get_issue(self, project_id: int, issue_iid: int) -> dict:
        r = await self._request("GET", f"/projects/{project_id}/issues/{issue_iid}")
        return r.json()

    async def update_issue(self, project_id: int, issue_iid: int, **fields) -> dict:
        r = await self._request("PUT", f"/projects/{project_id}/issues/{issue_iid}", json=fields)
        return r.json()

    async def get_project_labels(self, project_id: int) -> list[str]:
        r = await self._request("GET", f"/projects/{project_id}/labels", params={"per_page": 100})
        return [label["name"] for label in r.json()]

    async def post_issue_note(self, project_id: int, issue_iid: int, body: str) -> dict:
        r = await self._request(
            "POST", f"/projects/{project_id}/issues/{issue_iid}/notes",
            json={"body": body},
        )
        return r.json()

    # ── Release notes ────────────────────────────────────────────

    async def get_tags(self, project_id: int, per_page: int = 20) -> list[dict]:
        r = await self._request(
            "GET", f"/projects/{project_id}/repository/tags",
            params={"per_page": per_page, "order_by": "updated", "sort": "desc"},
        )
        return r.json()

    async def compare(self, project_id: int, from_ref: str, to_ref: str) -> dict:
        r = await self._request(
            "GET", f"/projects/{project_id}/repository/compare",
            params={"from": from_ref, "to": to_ref}, timeout=120,
        )
        return r.json()

    async def list_merge_requests(self, project_id: int, state: str = "merged",
                                  created_after: str | None = None, per_page: int = 100) -> list[dict]:
        params: dict = {"state": state, "per_page": per_page, "order_by": "created_at", "sort": "desc"}
        if created_after:
            params["created_after"] = created_after
        r = await self._request("GET", f"/projects/{project_id}/merge_requests", params=params, timeout=120)
        return r.json()

    async def update_release(self, project_id: int, tag_name: str, description: str) -> dict:
        r = await self._request(
            "PUT", f"/projects/{project_id}/releases/{tag_name}",
            json={"description": description},
        )
        return r.json()
