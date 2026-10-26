import json

import requests


class ApiClient:
    def __init__(self, base_url="http://127.0.0.1:8000", transport=None):
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.session = requests.Session()

    def _request(self, method, route, params=None, body=None, headers=None):
        if headers is None:
            request_headers = {"Accept-Language": "ru-RU"}
            if method in {"POST", "PUT", "PATCH"}:
                request_headers["Content-Type"] = "text/json"
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
            timeout=10,
        )

    def post_service_api_v2_submit_client(self, platform, user_agent, headers=None):
        return self._request(
            "POST",
            "/service/api/v2/submit-client",
            params={"platform": platform, "user_agent": user_agent},
            headers=headers,
        )

    def get_service_api_v2_collect_client(
        self, uid=None, created=None, platform=None, user_agent=None, headers=None
    ):
        params = {
            key: value
            for key, value in {
                "uid": uid,
                "created": created,
                "platform": platform,
                "user_agent": user_agent,
            }.items()
            if value is not None
        }
        return self._request(
            "GET",
            "/service/api/v2/collect-client",
            params=params,
            headers=headers,
        )

    def put_service_api_v2_adjust_client(self, uid, body, headers=None):
        return self._request(
            "PUT",
            f"/service/api/v2/adjust-client/{uid}",
            body=body,
            headers=headers,
        )

    def post_service_api_v2_submit_message(
        self, client, payload, tags="", headers=None
    ):
        return self._request(
            "POST",
            "/service/api/v2/submit-message",
            params={"client": client, "payload": payload, "tags": tags},
            headers=headers,
        )

    def get_service_api_v2_collect_message(
        self,
        client,
        uid=None,
        created=None,
        payload=None,
        tags=None,
        stage=None,
        launched=None,
        headers=None,
    ):
        params = {
            "uid": uid,
            "created": created,
            "payload": payload,
            "tags": tags,
            "stage": stage,
            "launched": launched,
        }
        params = {key: value for key, value in params.items() if value is not None}
        return self._request(
            "GET",
            f"/service/api/v2/collect-message/{client}",
            params=params,
            headers=headers,
        )

    def put_service_api_v2_adjust_message(self, uid, body, headers=None):
        return self._request(
            "PUT",
            f"/service/api/v2/adjust-message/{uid}",
            body=body,
            headers=headers,
        )

    def get_service_api_v2_collect_output(
        self,
        message,
        uid=None,
        created=None,
        response=None,
        stage=None,
        failure=None,
        cache_hit=None,
        headers=None,
    ):
        params = {
            "uid": uid,
            "created": created,
            "response": response,
            "stage": stage,
            "failure": failure,
            "cache_hit": cache_hit,
        }
        params = {key: value for key, value in params.items() if value is not None}
        return self._request(
            "GET",
            f"/service/api/v2/collect-output/{message}",
            params=params,
            headers=headers,
        )

    def get_service_api_v2_collect_report(self, headers=None):
        return self._request("GET", "/service/api/v2/collect-report", headers=headers)
