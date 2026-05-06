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
                log.error("MR not found — project_id=%s mr_iid=%s. Check token has access to this project", project_id, mr_iid)
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
