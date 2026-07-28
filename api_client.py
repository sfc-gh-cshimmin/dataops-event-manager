"""DataOps.live Admin API client."""

import requests
from typing import Optional


class DataOpsAPIError(Exception):
    """Raised when the DataOps API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class DataOpsClient:
    BASE_URL = "https://admin.dataops.live/api/v1"

    def __init__(self, token: str):
        self.token = token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None, timeout: int = 15) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=timeout)
        if resp.status_code >= 400:
            raise DataOpsAPIError(resp.status_code, resp.text)
        return resp.json()

    def _post(self, path: str, json_data: Optional[dict] = None, params: Optional[dict] = None, timeout: int = 30) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.post(url, headers=self._headers(), json=json_data, params=params, timeout=timeout)
        if resp.status_code >= 400:
            raise DataOpsAPIError(resp.status_code, resp.text)
        return resp.json()

    def _patch(self, path: str, json_data: Optional[dict] = None, timeout: int = 30) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.patch(url, headers=self._headers(), json=json_data, timeout=timeout)
        if resp.status_code >= 400:
            raise DataOpsAPIError(resp.status_code, resp.text)
        return resp.json()

    def health_check(self) -> dict:
        return self._get("/health_check")

    def get_events(self, search: Optional[str] = None) -> list:
        params = {}
        if search:
            params["search"] = search
        return self._get("/event_management/events-paginated", params=params)

    def get_all_events(self) -> list:
        return self._get("/event_management/events")

    def get_event(self, slug: str) -> dict:
        return self._get(f"/event_management/events/{slug}")

    def get_event_details(self, slug: str) -> dict:
        return self._get(f"/event_management/events/{slug}/details")

    def get_event_accounts(
        self, slug: str, page: int = 1, page_size: int = 100, search: Optional[str] = None
    ) -> dict:
        params = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        return self._get(f"/event_management/events/{slug}/accounts", params=params)

    def get_all_event_accounts(self, slug: str) -> list:
        all_accounts = []
        page = 1
        while True:
            data = self.get_event_accounts(slug, page=page, page_size=100)
            results = data if isinstance(data, list) else data.get("results", data.get("accounts", []))
            all_accounts.extend(results)
            if isinstance(data, dict) and data.get("next"):
                page += 1
            else:
                break
        return all_accounts

    def create_event(self, slug: str, payload: dict) -> dict:
        return self._post(f"/event_management/{slug}", json_data=payload)

    def patch_event(self, slug: str, payload: dict) -> dict:
        return self._patch(f"/event_management/{slug}", json_data=payload)

    def decommission_account(self, event_slug: str, account_id: int, remain_allocated: bool = True) -> dict:
        params = {"remain_allocated": str(remain_allocated).lower()}
        return self._post(
            f"/event_management/events/{event_slug}/accounts/{account_id}/decommission",
            params=params,
        )
