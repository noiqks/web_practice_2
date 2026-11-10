import json

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 10
REQUIRED_LANGUAGE = "ru-RU"
JSON_CONTENT_TYPE = "text/json"
BODY_METHODS = {"POST", "PUT", "PATCH"}

ALLOWED_MESSAGE_FILTERS = {
    "uid",
    "created",
    "payload",
    "tags",
    "stage",
    "launched",
}

ALLOWED_OUTPUT_FILTERS = {
    "uid",
    "created",
    "response",
    "stage",
    "failure",
    "cache_hit",
}


def _compact(values):
    return {
        key: value
        for key, value in values.items()
        if value is not None
    }


def _validate_filters(filters, allowed):
    unknown = set(filters) - allowed
    if unknown:
        raise TypeError(f"Unknown filters: {sorted(unknown)}")


class ApiClient:
    def __init__(
        self,
        base_url=DEFAULT_BASE_URL,
        transport=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.session = requests.Session()

    def _request(
        self,
        method,
        route,
        params=None,
        body=None,
        headers=None,
    ):
        if headers is None:
            request_headers = {"Accept-Language": REQUIRED_LANGUAGE}
            if method in BODY_METHODS:
                request_headers["Content-Type"] = JSON_CONTENT_TYPE
        else:
            request_headers = headers

        url = self.base_url + route
        encoded_body = None if body is None else json.dumps(body)

        if self.transport is not None:
            return self.transport.request(
                method,
                url,
                params=params,
                content=encoded_body,
                headers=request_headers,
            )

        return self.session.request(
            method,
            url,
            params=params,
            data=encoded_body,
            headers=request_headers,
            timeout=DEFAULT_TIMEOUT,
        )

    def post_service_api_v2_submit_client(
        self,
        platform,
        user_agent,
        headers=None,
    ):
        return self._request(
            "POST",
            "/service/api/v2/submit-client",
            params={"platform": platform, "user_agent": user_agent},
            headers=headers,
        )

    def get_service_api_v2_collect_client(
        self,
        **filters,
    ):
        headers = filters.pop("headers", None)
        params = _compact(filters)
        return self._request(
            "GET",
            "/service/api/v2/collect-client",
            params=params,
            headers=headers,
        )

    def put_service_api_v2_adjust_client(
        self,
        uid,
        body,
        headers=None,
    ):
        return self._request(
            "PUT",
            f"/service/api/v2/adjust-client/{uid}",
            body=body,
            headers=headers,
        )

    def post_service_api_v2_submit_message(
        self,
        client,
        payload,
        tags="",
        headers=None,
    ):
        return self._request(
            "POST",
            "/service/api/v2/submit-message",
            params={
                "client": client,
                "payload": payload,
                "tags": tags,
            },
            headers=headers,
        )

    def get_service_api_v2_collect_message(
        self,
        client,
        **filters,
    ):
        headers = filters.pop("headers", None)
        _validate_filters(filters, ALLOWED_MESSAGE_FILTERS)
        return self._request(
            "GET",
            f"/service/api/v2/collect-message/{client}",
            params=_compact(filters),
            headers=headers,
        )

    def put_service_api_v2_adjust_message(
        self,
        uid,
        body,
        headers=None,
    ):
        return self._request(
            "PUT",
            f"/service/api/v2/adjust-message/{uid}",
            body=body,
            headers=headers,
        )

    def get_service_api_v2_collect_output(
        self,
        message,
        **filters,
    ):
        headers = filters.pop("headers", None)
        _validate_filters(filters, ALLOWED_OUTPUT_FILTERS)
        return self._request(
            "GET",
            f"/service/api/v2/collect-output/{message}",
            params=_compact(filters),
            headers=headers,
        )

    def get_service_api_v2_collect_report(self, headers=None):
        return self._request(
            "GET",
            "/service/api/v2/collect-report",
            headers=headers,
        )
