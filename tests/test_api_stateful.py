from pathlib import Path

from fastapi.testclient import TestClient
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from src.api import create_app
from src.api_client import ApiClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = str(PROJECT_ROOT / "examples" / "input1.txt")

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_NOT_ACCEPTABLE = 406
HTTP_UNSUPPORTED_MEDIA_TYPE = 415

MAX_EXAMPLES = 5
STATEFUL_STEP_COUNT = 10

INITIAL_CACHE_HIT = 0
TEST_RESPONSE = "Task not executed in test mode"

MISSING_UID = 999999


class ApiStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.app = create_app(
            test_mode=True,
            database_url="sqlite:///:memory:",
        )
        self.transport = TestClient(self.app)
        self.api = ApiClient(transport=self.transport)

        self.model = {
            "clients": {},
            "messages": {},
            "outputs": {},
        }

    def teardown(self):
        self.model["clients"].clear()
        self.model["messages"].clear()
        self.model["outputs"].clear()

    def _first_client_uid(self):
        if not self.model["clients"]:
            return None
        return list(self.model["clients"].keys())[0]

    def _first_message_uid(self):
        if not self.model["messages"]:
            return None
        return list(self.model["messages"].keys())[0]

    @rule(
        platform=st.text(alphabet="abc", min_size=1, max_size=5),
        user_agent=st.text(alphabet="xyz", min_size=1, max_size=5),
    )
    def create_client(self, platform, user_agent):
        response = self.api.post_service_api_v2_submit_client(
            platform=platform,
            user_agent=user_agent,
        )
        assert response.status_code == HTTP_OK
        client = response.json()
        self.model["clients"][client["uid"]] = client

    @rule(
        platform=st.text(alphabet="abc", min_size=1, max_size=5),
        user_agent=st.text(alphabet="xyz", min_size=1, max_size=5),
    )
    def update_existing_client(self, platform, user_agent):
        uid = self._first_client_uid()
        if uid is None:
            return

        response = self.api.put_service_api_v2_adjust_client(
            uid,
            {"platform": platform, "user_agent": user_agent},
        )
        if response.status_code == HTTP_OK:
            self.model["clients"][uid]["platform"] = platform
            self.model["clients"][uid]["user_agent"] = user_agent

    @rule()
    def update_missing_client(self):
        response = self.api.put_service_api_v2_adjust_client(
            MISSING_UID,
            {"platform": "x"},
        )
        assert response.status_code == HTTP_NOT_FOUND

    @rule()
    def update_client_with_unknown_field(self):
        uid = self._first_client_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_client(
            uid,
            {"unknown": "field"},
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def update_client_with_bad_created_type(self):
        uid = self._first_client_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_client(
            uid,
            {"created": "not-an-integer"},
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def update_client_with_bad_platform_type(self):
        uid = self._first_client_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_client(
            uid,
            {"platform": 123},
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule(
        tags=st.text(alphabet="abc", min_size=1, max_size=5),
    )
    def create_message(self, tags):
        client_uid = self._first_client_uid()
        if client_uid is None:
            return

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags=tags,
        )
        assert response.status_code == HTTP_OK

        message = response.json()
        self.model["messages"][message["uid"]] = message

        outputs_response = self.api.get_service_api_v2_collect_output(
            message["uid"]
        )
        assert outputs_response.status_code == HTTP_OK
        actual_output = outputs_response.json()[0]

        expected_output = {
            "uid": actual_output["uid"],
            "created": actual_output["created"],
            "message": message["uid"],
            "response": TEST_RESPONSE,
            "stage": "skipped",
            "failure": "",
            "cache_hit": INITIAL_CACHE_HIT,
        }
        self.model["outputs"][actual_output["uid"]] = expected_output

    @rule()
    def create_message_for_missing_client(self):
        response = self.api.post_service_api_v2_submit_message(
            client=MISSING_UID,
            payload=EXAMPLE_INPUT,
            tags="missing",
        )
        assert response.status_code == HTTP_NOT_FOUND

    @rule(
        payload=st.text(alphabet="abc", min_size=1, max_size=5),
        tags=st.text(alphabet="xyz", min_size=1, max_size=5),
    )
    def update_existing_message(self, payload, tags):
        uid = self._first_message_uid()
        if uid is None:
            return

        response = self.api.put_service_api_v2_adjust_message(
            uid,
            {"payload": payload, "tags": tags},
        )
        if response.status_code == HTTP_OK:
            self.model["messages"][uid]["payload"] = payload
            self.model["messages"][uid]["tags"] = tags

    @rule()
    def update_missing_message(self):
        response = self.api.put_service_api_v2_adjust_message(
            MISSING_UID,
            {"tags": "missing"},
        )
        assert response.status_code == HTTP_NOT_FOUND

    @rule()
    def update_message_with_unknown_field(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_message(
            uid,
            {"unknown": "field"},
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def update_message_with_bad_launched_type(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_message(
            uid,
            {"launched": "later"},
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def update_message_with_non_object_body(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        response = self.api.put_service_api_v2_adjust_message(
            uid,
            ["not", "an", "object"],
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def update_message_with_empty_body(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        response = self.api._request(
            "PUT",
            f"/service/api/v2/adjust-message/{uid}",
            headers={
                "Content-Type": "text/json",
                "Accept-Language": "ru-RU",
            },
        )
        assert response.status_code == HTTP_BAD_REQUEST

    @rule()
    def request_without_content_type(self):
        response = self.api.post_service_api_v2_submit_client(
            "platform",
            "agent",
            headers={"Accept-Language": "ru-RU"},
        )
        assert response.status_code == HTTP_UNSUPPORTED_MEDIA_TYPE

    @rule()
    def request_without_language(self):
        response = self.api.get_service_api_v2_collect_client(headers={})
        assert response.status_code == HTTP_NOT_ACCEPTABLE

    @rule()
    def request_with_wrong_language(self):
        response = self.api.get_service_api_v2_collect_report(
            headers={"Accept-Language": "en-US"},
        )
        assert response.status_code == HTTP_NOT_ACCEPTABLE

    @rule()
    def request_docs_without_language(self):
        response = self.api._request(
            "GET",
            "/docs",
            headers={},
        )
        assert response.status_code == HTTP_OK

    @rule()
    def collect_report(self):
        response = self.api.get_service_api_v2_collect_report()
        assert response.status_code == HTTP_OK

    @rule()
    def collect_output_invalid_filter(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        response = self.api.get_service_api_v2_collect_output(
            uid,
            stage="not-a-real-stage",
            cache_hit=1,
        )
        assert response.status_code == HTTP_OK
        assert response.json() == []

    @rule()
    def collect_output_by_existing_output(self):
        if not self.model["outputs"]:
            return
        out_uid = list(self.model["outputs"].keys())[0]
        expected = self.model["outputs"][out_uid]
        response = self.api.get_service_api_v2_collect_output(
            expected["message"],
            uid=out_uid,
            created=expected["created"],
            response=expected["response"],
            stage=expected["stage"],
            failure=expected["failure"],
            cache_hit=expected["cache_hit"],
        )
        assert response.status_code == HTTP_OK
        assert len(response.json()) == 1

    @rule()
    def collect_client_with_filters(self):
        uid = self._first_client_uid()
        if uid is None:
            return
        expected = self.model["clients"][uid]
        response = self.api.get_service_api_v2_collect_client(
            uid=uid,
            created=expected["created"],
            platform=expected["platform"],
            user_agent=expected["user_agent"],
        )
        assert response.status_code == HTTP_OK
        assert len(response.json()) == 1

    @rule()
    def collect_message_with_filters(self):
        uid = self._first_message_uid()
        if uid is None:
            return
        expected = self.model["messages"][uid]
        response = self.api.get_service_api_v2_collect_message(
            expected["client"],
            uid=uid,
            created=expected["created"],
            payload=expected["payload"],
            tags=expected["tags"],
            stage=expected["stage"],
            launched=expected["launched"],
        )
        assert response.status_code == HTTP_OK
        assert len(response.json()) == 1

    @invariant()
    def check_clients_match_model(self):
        response = self.api.get_service_api_v2_collect_client()
        assert response.status_code == HTTP_OK
        actual_clients = response.json()

        assert len(actual_clients) == len(self.model["clients"])

        for client in actual_clients:
            uid = client["uid"]
            assert uid in self.model["clients"]
            expected = self.model["clients"][uid]
            assert client["platform"] == expected["platform"]
            assert client["user_agent"] == expected["user_agent"]

    @invariant()
    def check_messages_and_outputs_match_model(self):
        for client_uid in self.model["clients"]:
            response = self.api.get_service_api_v2_collect_message(
                client_uid
            )
            assert response.status_code == HTTP_OK
            actual_messages = response.json()

            expected_msg_count = sum(
                1
                for m in self.model["messages"].values()
                if m["client"] == client_uid
            )
            assert len(actual_messages) == expected_msg_count

            for msg in actual_messages:
                uid = msg["uid"]
                assert uid in self.model["messages"]
                expected = self.model["messages"][uid]
                assert msg["payload"] == expected["payload"]
                assert msg["tags"] == expected["tags"]

                out_response = (
                    self.api.get_service_api_v2_collect_output(uid)
                )
                assert out_response.status_code == HTTP_OK
                actual_outputs = out_response.json()
                assert len(actual_outputs) == 1

                out = actual_outputs[0]
                out_uid = out["uid"]
                assert out_uid in self.model["outputs"]
                expected_out = self.model["outputs"][out_uid]
                assert out["response"] == expected_out["response"]
                assert out["stage"] == expected_out["stage"]


def test_api_state_machine():
    run_state_machine_as_test(
        ApiStateMachine,
        settings=settings(
            max_examples=MAX_EXAMPLES,
            stateful_step_count=STATEFUL_STEP_COUNT,
            deadline=None,
        ),
    )
