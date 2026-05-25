import logging

import httpx

from . import config

log = logging.getLogger(__name__)


class GitLabClient:
    def __init__(self, url: str = config.GITLAB_URL, token: str = config.GITLAB_TOKEN):
        self.base = url.rstrip("/") + "/api/v4"
        self.headers = {"PRIVATE-TOKEN": token}

    async def get_mr(self, project_id: int, mr_iid: int) -> dict:
        url = f"{self.base}/projects/{project_id}/merge_requests/{mr_iid}"
        log.debug("GET %s", url)
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(url, headers=self.headers)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            log.error("Cannot connect to GitLab at %s — is it reachable?", config.GITLAB_URL)
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                log.error("GitLab auth failed (401) — check GITLAB_TOKEN has 'api' scope")
            elif e.response.status_code == 404:
                log.error("MR not found — project_id=%s mr_iid=%s. Check token has access to this project", project_id,
                          mr_iid)
            else:
                log.error("GitLab returned HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise

    async def get_diffs(self, project_id: int, mr_iid: int) -> list[dict]:
        diffs: list[dict] = []
        page = 1
        per_page = 50
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                while True:
                    url = f"{self.base}/projects/{project_id}/merge_requests/{mr_iid}/diffs"
                    log.debug("GET %s (page=%d)", url, page)
                    r = await c.get(url, params={"page": page, "per_page": per_page}, headers=self.headers)
                    r.raise_for_status()
                    batch = r.json()
                    if not batch:
                        break
                    diffs.extend(batch)
                    if len(batch) < per_page:
                        break
                    page += 1
        except httpx.ConnectError:
            log.error("Cannot connect to GitLab at %s while fetching diffs", config.GITLAB_URL)
            raise
        except httpx.HTTPStatusError as e:
            log.error("GitLab returned HTTP %s while fetching diffs: %s", e.response.status_code, e.response.text[:300])
            raise
        log.debug("Fetched %d diff entries across %d page(s)", len(diffs), page)
        return diffs

    async def post_note(self, project_id: int, mr_iid: int, body: str) -> dict:
        url = f"{self.base}/projects/{project_id}/merge_requests/{mr_iid}/notes"
        log.debug("POST %s (%d chars)", url, len(body))
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(url, headers=self.headers, json={"body": body})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            log.error("Failed to post note to MR: HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise

    # ── Push events ──────────────────────────────────────────────

    async def get_commit_diff(self, project_id: int, sha: str) -> list[dict]:
        url = f"{self.base}/projects/{project_id}/repository/commits/{sha}/diff"
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(url, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def post_commit_comment(self, project_id: int, sha: str, body: str) -> dict:
        url = f"{self.base}/projects/{project_id}/repository/commits/{sha}/comments"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers=self.headers, json={"note": body})
            r.raise_for_status()
            return r.json()

    # ── Pipeline events ──────────────────────────────────────────

    async def get_pipeline_jobs(self, project_id: int, pipeline_id: int) -> list[dict]:
        url = f"{self.base}/projects/{project_id}/pipelines/{pipeline_id}/jobs"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url, params={"per_page": 100}, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def get_job_log(self, project_id: int, job_id: int, tail_chars: int = 20000) -> str:
        url = f"{self.base}/projects/{project_id}/jobs/{job_id}/trace"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url, headers=self.headers)
            r.raise_for_status()
            text = r.text
            if len(text) > tail_chars:
                text = text[-tail_chars:]
            return text

    # ── MR description ───────────────────────────────────────────

    async def update_mr(self, project_id: int, mr_iid: int, **fields) -> dict:
        url = f"{self.base}/projects/{project_id}/merge_requests/{mr_iid}"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(url, headers=self.headers, json=fields)
            r.raise_for_status()
            return r.json()

    # ── Issue triage ─────────────────────────────────────────────

    async def get_issue(self, project_id: int, issue_iid: int) -> dict:
        url = f"{self.base}/projects/{project_id}/issues/{issue_iid}"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def update_issue(self, project_id: int, issue_iid: int, **fields) -> dict:
        url = f"{self.base}/projects/{project_id}/issues/{issue_iid}"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(url, headers=self.headers, json=fields)
            r.raise_for_status()
            return r.json()

    async def get_project_labels(self, project_id: int) -> list[str]:
        url = f"{self.base}/projects/{project_id}/labels"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url, params={"per_page": 100}, headers=self.headers)
            r.raise_for_status()
            return [label["name"] for label in r.json()]

    async def post_issue_note(self, project_id: int, issue_iid: int, body: str) -> dict:
        url = f"{self.base}/projects/{project_id}/issues/{issue_iid}/notes"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers=self.headers, json={"body": body})
            r.raise_for_status()
            return r.json()

    # ── Release notes ────────────────────────────────────────────

    async def get_tags(self, project_id: int, per_page: int = 20) -> list[dict]:
        url = f"{self.base}/projects/{project_id}/repository/tags"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(url, params={"per_page": per_page, "order_by": "updated", "sort": "desc"},
                            headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def compare(self, project_id: int, from_ref: str, to_ref: str) -> dict:
        url = f"{self.base}/projects/{project_id}/repository/compare"
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(url, params={"from": from_ref, "to": to_ref}, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def list_merge_requests(self, project_id: int, state: str = "merged",
                                  created_after: str | None = None, per_page: int = 100) -> list[dict]:
        url = f"{self.base}/projects/{project_id}/merge_requests"
        params: dict = {"state": state, "per_page": per_page, "order_by": "created_at", "sort": "desc"}
        if created_after:
            params["created_after"] = created_after
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(url, params=params, headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def update_release(self, project_id: int, tag_name: str, description: str) -> dict:
        url = f"{self.base}/projects/{project_id}/releases/{tag_name}"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(url, headers=self.headers, json={"description": description})
            r.raise_for_status()
            return r.json()
