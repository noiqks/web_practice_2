from pathlib import Path

from fastapi.testclient import TestClient
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from src.api import create_app
from src.api_client import ApiClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = str(PROJECT_ROOT / "examples" / "input1.txt")
MISSING_INPUT = str(
    PROJECT_ROOT / "examples" / "file-that-does-not-exist.txt"
)


class ApiStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()

        self.app = create_app(test_mode=True)
        self.transport = TestClient(self.app)
        self.api = ApiClient(transport=self.transport)

        self.client_ids = []
        self.message_ids = []

    def create_initial_client(self):
        response = self.api.post_service_api_v2_submit_client(
            platform="test-platform",
            user_agent="state-machine-agent",
        )

        assert response.status_code == 200

        client = response.json()
        self.client_ids.append(client["uid"])

        return client

    def check_initial_client(self, client):
        response = self.api.get_service_api_v2_collect_client()

        assert response.status_code == 200
        assert response.json()

        response = self.api.get_service_api_v2_collect_client(
            uid=client["uid"],
            created=client["created"],
        )

        assert response.status_code == 200
        assert len(response.json()) == 1

        response = self.api.put_service_api_v2_adjust_client(
            client["uid"],
            {"platform": "test-platform-updated"},
        )

        assert response.status_code == 200
        assert response.json()["platform"] == "test-platform-updated"

    def create_initial_message(self, client_uid):
        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="initial",
        )

        assert response.status_code == 200

        message = response.json()
        self.message_ids.append(message["uid"])

        return message

    def check_initial_message(self, client_uid, message):
        response = self.api.get_service_api_v2_collect_message(
            client_uid
        )

        assert response.status_code == 200
        assert response.json()

        filtered = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message["uid"],
            created=message["created"],
            payload=message["payload"],
            tags="initial",
            stage="skipped",
            launched=0,
        )

        assert filtered.status_code == 200
        assert len(filtered.json()) == 1

    def check_initial_output(self, message_uid):
        response = self.api.get_service_api_v2_collect_output(
            message_uid
        )

        assert response.status_code == 200
        assert response.json()

        output = response.json()[0]

        filtered = self.api.get_service_api_v2_collect_output(
            message_uid,
            uid=output["uid"],
            created=output["created"],
            response=output["response"],
            stage=output["stage"],
            failure=output["failure"],
            cache_hit=output["cache_hit"],
        )

        assert filtered.status_code == 200
        assert len(filtered.json()) == 1

    @initialize()
    def create_initial_records(self):
        client = self.create_initial_client()
        self.check_initial_client(client)

        message = self.create_initial_message(
            client["uid"]
        )
        self.check_initial_message(
            client["uid"],
            message,
        )
        self.check_initial_output(message["uid"])

        response = self.api.get_service_api_v2_collect_report()

        assert response.status_code == 200

    @rule(
        platform=st.text(
            alphabet="abcdef012345",
            min_size=1,
            max_size=10,
        ),
        user_agent=st.text(
            alphabet="uvwxyz012345",
            min_size=1,
            max_size=12,
        ),
    )
    def submit_and_find_client(self, platform, user_agent):
        response = self.api.post_service_api_v2_submit_client(
            platform,
            user_agent,
        )

        assert response.status_code == 200

        client = response.json()
        self.client_ids.append(client["uid"])

        found = self.api.get_service_api_v2_collect_client(
            uid=client["uid"],
            created=client["created"],
            platform=platform,
            user_agent=user_agent,
        )

        assert found.status_code == 200
        assert len(found.json()) == 1
        assert found.json()[0]["uid"] == client["uid"]

    @rule()
    def check_unique_client_ids(self):
        first_response = self.api.post_service_api_v2_submit_client(
            platform="Windows",
            user_agent="TestClient1",
        )

        second_response = self.api.post_service_api_v2_submit_client(
            platform="Linux",
            user_agent="TestClient2",
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        first_client = first_response.json()
        second_client = second_response.json()

        assert first_client["uid"] != second_client["uid"]

        self.client_ids.append(first_client["uid"])
        self.client_ids.append(second_client["uid"])

    @rule()
    def check_client_fields_are_not_mixed(self):
        response = self.api.post_service_api_v2_submit_client(
            platform="Windows-test",
            user_agent="Agent-test-123",
        )

        assert response.status_code == 200

        client = response.json()

        assert client["platform"] == "Windows-test"
        assert client["user_agent"] == "Agent-test-123"
        assert isinstance(client["uid"], int)
        assert isinstance(client["created"], int)

        found = self.api.get_service_api_v2_collect_client(
            uid=client["uid"],
            platform="Windows-test",
            user_agent="Agent-test-123",
        )

        assert found.status_code == 200
        assert len(found.json()) == 1
        assert found.json()[0] == client

    @rule(
        platform=st.text(
            alphabet="abcdef012345",
            min_size=1,
            max_size=10,
        ),
        user_agent=st.text(
            alphabet="uvwxyz012345",
            min_size=1,
            max_size=12,
        ),
    )
    def update_client(self, platform, user_agent):
        uid = self.client_ids[0]

        response = self.api.put_service_api_v2_adjust_client(
            uid,
            {
                "platform": platform,
                "user_agent": user_agent,
            },
        )

        assert response.status_code == 200

        client = response.json()

        assert client["platform"] == platform
        assert client["user_agent"] == user_agent

        missing = self.api.put_service_api_v2_adjust_client(
            999999,
            {"platform": "x"},
        )

        assert missing.status_code == 404

        bad_created = self.api.put_service_api_v2_adjust_client(
            uid,
            {"created": "not-an-integer"},
        )

        assert bad_created.status_code == 400

        bad_type = self.api.put_service_api_v2_adjust_client(
            uid,
            {"platform": 123},
        )

        assert bad_type.status_code == 400

    @rule(
        tags=st.text(
            alphabet="tag012345",
            max_size=8,
        )
    )
    def submit_and_find_message(self, tags):
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags=tags,
        )

        assert response.status_code == 200

        message = response.json()
        message_uid = message["uid"]
        self.message_ids.append(message_uid)

        found = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message_uid,
            tags=tags,
        )

        assert found.status_code == 200
        assert len(found.json()) == 1
        assert found.json()[0]["uid"] == message_uid

        missing_client = (
            self.api.post_service_api_v2_submit_message(
                client=999999,
                payload=EXAMPLE_INPUT,
                tags=tags,
            )
        )

        assert missing_client.status_code == 404

    def create_field_check_message(self):
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="field-check",
        )

        assert response.status_code == 200

        return client_uid, response.json()

    def check_message_fields(self, client_uid, message):
        assert message["client"] == client_uid
        assert message["payload"] == EXAMPLE_INPUT
        assert message["tags"] == "field-check"
        assert message["stage"] == "skipped"
        assert message["launched"] == 0

        by_stage = (
            self.api.get_service_api_v2_collect_message(
                client_uid,
                uid=message["uid"],
                stage="skipped",
            )
        )

        assert by_stage.status_code == 200
        assert len(by_stage.json()) == 1

    def check_message_launched_filter(self, client_uid, message):
        by_launched = (
            self.api.get_service_api_v2_collect_message(
                client_uid,
                uid=message["uid"],
                launched=0,
            )
        )

        assert by_launched.status_code == 200
        assert len(by_launched.json()) == 1

        wrong_stage = (
            self.api.get_service_api_v2_collect_message(
                client_uid,
                uid=message["uid"],
                stage="0",
            )
        )

        assert wrong_stage.status_code == 200
        assert wrong_stage.json() == []

    @rule()
    def check_message_stage_and_launched_are_separate(self):
        client_uid, message = self.create_field_check_message()

        self.check_message_fields(
            client_uid,
            message,
        )

        self.check_message_launched_filter(
            client_uid,
            message,
        )

    @rule(
        payload=st.text(
            alphabet="payload012345",
            min_size=1,
            max_size=12,
        )
    )
    def update_message(self, payload):
        uid = self.message_ids[0]

        response = self.api.put_service_api_v2_adjust_message(
            uid,
            {
                "payload": payload,
                "tags": "changed",
            },
        )

        assert response.status_code == 200

        message = response.json()

        assert message["payload"] == payload
        assert message["tags"] == "changed"

        launched = self.api.put_service_api_v2_adjust_message(
            uid,
            {"launched": 123},
        )

        assert launched.status_code == 200
        assert launched.json()["launched"] == 123

        bad_launched = self.api.put_service_api_v2_adjust_message(
            uid,
            {"launched": "later"},
        )

        assert bad_launched.status_code == 400

        missing = self.api.put_service_api_v2_adjust_message(
            999999,
            {"tags": "missing"},
        )

        assert missing.status_code == 404

    @rule()
    def check_message_update_preserves_other_fields(self):
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="before-update",
        )

        assert response.status_code == 200

        message = response.json()

        updated = self.api.put_service_api_v2_adjust_message(
            message["uid"],
            {"tags": "after-update"},
        )

        assert updated.status_code == 200

        result = updated.json()

        assert result["uid"] == message["uid"]
        assert result["client"] == message["client"]
        assert result["created"] == message["created"]
        assert result["payload"] == message["payload"]
        assert result["tags"] == "after-update"
        assert result["stage"] == message["stage"]
        assert result["launched"] == message["launched"]

    def create_output_check_message(self):
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="output-field-check",
        )

        assert response.status_code == 200

        return response.json()

    def get_and_check_output(self, message):
        response = self.api.get_service_api_v2_collect_output(
            message["uid"]
        )

        assert response.status_code == 200
        assert response.json()

        output = response.json()[0]

        assert output["message"] == message["uid"]
        assert output["stage"] == "skipped"
        assert output["response"] == (
            "Task not executed in test mode"
        )
        assert output["failure"] == ""
        assert output["cache_hit"] == 0
        assert isinstance(output["uid"], int)
        assert isinstance(output["created"], int)

        return output

    def check_output_filters(self, message, output):
        filtered = self.api.get_service_api_v2_collect_output(
            message["uid"],
            uid=output["uid"],
            created=output["created"],
            response="Task not executed in test mode",
            stage="skipped",
            failure="",
            cache_hit=0,
        )

        assert filtered.status_code == 200
        assert len(filtered.json()) == 1
        assert filtered.json()[0] == output

        wrong_stage = (
            self.api.get_service_api_v2_collect_output(
                message["uid"],
                stage="0",
            )
        )

        assert wrong_stage.status_code == 200
        assert wrong_stage.json() == []

    def check_wrong_cache_hit(self, message):
        wrong_cache_hit = (
            self.api.get_service_api_v2_collect_output(
                message["uid"],
                cache_hit=1,
            )
        )

        assert wrong_cache_hit.status_code == 200
        assert wrong_cache_hit.json() == []

    @rule()
    def check_output_fields_are_not_mixed(self):
        message = self.create_output_check_message()
        output = self.get_and_check_output(message)

        self.check_output_filters(
            message,
            output,
        )

        self.check_wrong_cache_hit(message)

    @rule()
    def read_outputs_and_report(self):
        message_uid = self.message_ids[0]

        response = self.api.get_service_api_v2_collect_output(
            message_uid
        )

        assert response.status_code == 200
        assert response.json()

        output = response.json()[0]

        filtered = self.api.get_service_api_v2_collect_output(
            message_uid,
            uid=output["uid"],
            created=output["created"],
            response=output["response"],
            stage=output["stage"],
            failure=output["failure"],
            cache_hit=output["cache_hit"],
        )

        assert filtered.status_code == 200
        assert len(filtered.json()) == 1

        invalid = self.api.get_service_api_v2_collect_output(
            message_uid,
            stage="not-a-real-stage",
            cache_hit=1,
        )

        assert invalid.status_code == 200
        assert invalid.json() == []

        report = self.api.get_service_api_v2_collect_report()

        assert report.status_code == 200

    def check_missing_content_type(self):
        response = self.api.post_service_api_v2_submit_client(
            "platform",
            "agent",
            headers={"Accept-Language": "ru-RU"},
        )

        assert response.status_code == 415

    def check_missing_language(self):
        response = self.api.get_service_api_v2_collect_client(
            headers={}
        )

        assert response.status_code == 406

        response = self.api.get_service_api_v2_collect_report(
            headers={"Accept-Language": "en-US"}
        )

        assert response.status_code == 406

    def check_header_priority(self):
        response = self.api.post_service_api_v2_submit_client(
            "platform",
            "agent",
            headers={},
        )

        assert response.status_code == 415

        docs = self.api._request(
            "GET",
            "/docs",
            headers={},
        )

        assert docs.status_code == 200

    @rule()
    def check_required_headers(self):
        self.check_missing_content_type()
        self.check_missing_language()
        self.check_header_priority()

    @rule()
    def test_invalid_update_body(self):
        message_uid = self.message_ids[0]

        response = self.api.put_service_api_v2_adjust_message(
            message_uid,
            ["not", "an", "object"],
        )

        assert response.status_code == 400

        response = self.api.put_service_api_v2_adjust_client(
            self.client_ids[0],
            {"unknown": "field"},
        )

        assert response.status_code == 400

        response = self.api.put_service_api_v2_adjust_message(
            message_uid,
            {"unknown": "field"},
        )

        assert response.status_code == 400

        response = self.api._request(
            "PUT",
            f"/service/api/v2/adjust-message/{message_uid}",
            headers={
                "Content-Type": "text/json",
                "Accept-Language": "ru-RU",
            },
        )

        assert response.status_code == 400

    def execute_successful_cli(self, client_uid):
        success = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="real-cli",
        )

        assert success.status_code == 200

        message = success.json()
        self.message_ids.append(message["uid"])

        outputs = self.api.get_service_api_v2_collect_output(
            message["uid"]
        )

        assert outputs.status_code == 200
        assert outputs.json()[0]["stage"] == "completed"
        assert len(outputs.json()[0]["response"]) == 32

    def execute_failed_cli(self, client_uid):
        failure = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=MISSING_INPUT,
            tags="missing-file",
        )

        assert failure.status_code == 200

        message = failure.json()
        self.message_ids.append(message["uid"])

        outputs = self.api.get_service_api_v2_collect_output(
            message["uid"]
        )

        assert outputs.status_code == 200
        assert outputs.json()[0]["stage"] == "failed"
        assert outputs.json()[0]["failure"]

    @rule()
    def execute_cli_success_and_failure(self):
        client_uid = self.client_ids[0]

        self.app.state.test_mode = False

        self.execute_successful_cli(client_uid)
        self.execute_failed_cli(client_uid)

        self.app.state.test_mode = True


TestApiStateMachine = ApiStateMachine.TestCase

TestApiStateMachine.settings = settings(
    max_examples=10,
    stateful_step_count=12,
    deadline=None,
)
