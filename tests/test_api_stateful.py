from pathlib import Path

from fastapi.testclient import TestClient
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from src.api import create_app
from src.api_client import ApiClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = str(PROJECT_ROOT / "examples" / "input1.txt")
MISSING_INPUT = str(PROJECT_ROOT / "examples" / "file-that-does-not-exist.txt")


class ApiStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.app = create_app(test_mode=True)
        self.transport = TestClient(self.app)
        self.api = ApiClient(transport=self.transport)
        self.client_ids = []
        self.message_ids = []

    @initialize()
    def create_initial_records(self):
        response = self.api.post_service_api_v2_submit_client(
            platform="test-platform", user_agent="state-machine-agent"
        )
        assert response.status_code == 200
        client_uid = response.json()["uid"]
        self.client_ids.append(client_uid)

        response = self.api.get_service_api_v2_collect_client()
        assert response.status_code == 200
        assert response.json()

        response = self.api.get_service_api_v2_collect_client(
            uid=client_uid, created=response.json()[0]["created"]
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

        response = self.api.put_service_api_v2_adjust_client(
            client_uid, {"platform": "test-platform-updated"}
        )
        assert response.status_code == 200

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload="unused-in-test-mode.txt",
            tags="initial",
        )
        assert response.status_code == 200
        message = response.json()
        message_uid = message["uid"]
        self.message_ids.append(message_uid)

        response = self.api.get_service_api_v2_collect_message(client_uid)
        assert response.status_code == 200
        assert response.json()
        filtered_messages = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message_uid,
            created=message["created"],
            payload=message["payload"],
            stage="skipped",
            tags="initial",
            launched=0,
        )
        assert filtered_messages.status_code == 200
        assert filtered_messages.json()

        response = self.api.put_service_api_v2_adjust_message(
            message_uid, {"tags": "initial-updated"}
        )
        assert response.status_code == 200

        response = self.api.get_service_api_v2_collect_output(message_uid)
        assert response.status_code == 200
        assert response.json()
        output = response.json()[0]
        filtered_outputs = self.api.get_service_api_v2_collect_output(
            message_uid,
            uid=output["uid"],
            created=output["created"],
            response=output["response"],
            stage=output["stage"],
            failure=output["failure"],
            cache_hit=output["cache_hit"],
        )
        assert filtered_outputs.status_code == 200
        assert len(filtered_outputs.json()) == 1

        response = self.api.get_service_api_v2_collect_report()
        assert response.status_code == 200
        assert response.json()

    @rule(
        platform=st.text(alphabet="abcdef012345", min_size=1, max_size=10),
        user_agent=st.text(alphabet="uvwxyz012345", min_size=1, max_size=12),
    )
    def submit_and_find_client(self, platform, user_agent):
        response = self.api.post_service_api_v2_submit_client(platform, user_agent)
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

    @rule()
    def check_client_fields_are_not_mixed(self):
        """Check that client fields keep their own values."""
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

    @rule()
    def check_message_stage_and_launched_are_separate(self):
        """Check that message stage is not replaced by launched."""
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="field-check",
        )
        assert response.status_code == 200

        message = response.json()
        assert message["client"] == client_uid
        assert message["payload"] == EXAMPLE_INPUT
        assert message["tags"] == "field-check"
        assert message["stage"] == "skipped"
        assert message["launched"] == 0
        assert message["stage"] != message["launched"]

        by_stage = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message["uid"],
            stage="skipped",
        )
        assert by_stage.status_code == 200
        assert len(by_stage.json()) == 1
        assert by_stage.json()[0]["stage"] == "skipped"

        by_launched = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message["uid"],
            launched=0,
        )
        assert by_launched.status_code == 200
        assert len(by_launched.json()) == 1
        assert by_launched.json()[0]["launched"] == 0

        wrong_stage = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message["uid"],
            stage="0",
        )
        assert wrong_stage.status_code == 200
        assert wrong_stage.json() == []

        wrong_launched = self.api.get_service_api_v2_collect_message(
            client_uid,
            uid=message["uid"],
            launched=123456,
        )
        assert wrong_launched.status_code == 200
        assert wrong_launched.json() == []

    @rule()
    def check_output_fields_are_not_mixed(self):
        """Check that output fields keep their own values."""
        client_uid = self.client_ids[0]

        message_response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="output-field-check",
        )
        assert message_response.status_code == 200
        message = message_response.json()

        response = self.api.get_service_api_v2_collect_output(message["uid"])
        assert response.status_code == 200
        assert response.json()

        output = response.json()[0]
        assert output["message"] == message["uid"]
        assert output["stage"] == "skipped"
        assert output["response"] == "Task not executed in test mode"
        assert output["failure"] == ""
        assert output["cache_hit"] == 0
        assert isinstance(output["uid"], int)
        assert isinstance(output["created"], int)

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

        wrong_stage = self.api.get_service_api_v2_collect_output(
            message["uid"],
            stage="0",
        )
        assert wrong_stage.status_code == 200
        assert wrong_stage.json() == []

        wrong_cache_hit = self.api.get_service_api_v2_collect_output(
            message["uid"],
            cache_hit=1,
        )
        assert wrong_cache_hit.status_code == 200
        assert wrong_cache_hit.json() == []

    @rule()
    def check_message_update_preserves_other_fields(self):
        """Check that updating one message field preserves the others."""
        client_uid = self.client_ids[0]

        response = self.api.post_service_api_v2_submit_message(
            client=client_uid,
            payload=EXAMPLE_INPUT,
            tags="before-update",
        )
        assert response.status_code == 200
        message = response.json()

        old_uid = message["uid"]
        old_client = message["client"]
        old_created = message["created"]
        old_stage = message["stage"]
        old_launched = message["launched"]

        updated = self.api.put_service_api_v2_adjust_message(
            old_uid,
            {"tags": "after-update"},
        )
        assert updated.status_code == 200

        result = updated.json()
        assert result["uid"] == old_uid
        assert result["client"] == old_client
        assert result["created"] == old_created
        assert result["payload"] == EXAMPLE_INPUT
        assert result["tags"] == "after-update"
        assert result["stage"] == old_stage
        assert result["launched"] == old_launched

    @rule(
        platform=st.text(alphabet="abcdef012345", min_size=1, max_size=10),
        user_agent=st.text(alphabet="uvwxyz012345", min_size=1, max_size=12),
    )
    def update_client(self, platform, user_agent):
        uid = self.client_ids[0]
        response = self.api.put_service_api_v2_adjust_client(
            uid, {"platform": platform, "user_agent": user_agent}
        )
        assert response.status_code == 200
        assert response.json()["platform"] == platform

        missing = self.api.put_service_api_v2_adjust_client(999999, {"platform": "x"})
        assert missing.status_code == 404

        bad_created = self.api.put_service_api_v2_adjust_client(
            uid, {"created": "not-an-integer"}
        )
        assert bad_created.status_code == 400
        bad_type = self.api.put_service_api_v2_adjust_client(uid, {"platform": 123})
        assert bad_type.status_code == 400

    @rule(tags=st.text(alphabet="tag012345", max_size=8))
    def submit_and_find_message(self, tags):
        response = self.api.post_service_api_v2_submit_message(
            client=self.client_ids[0], payload=EXAMPLE_INPUT, tags=tags
        )
        assert response.status_code == 200
        message_uid = response.json()["uid"]
        self.message_ids.append(message_uid)

        found = self.api.get_service_api_v2_collect_message(
            self.client_ids[0], tags=tags
        )
        assert found.status_code == 200
        assert any(item["uid"] == message_uid for item in found.json())

        missing_client = self.api.post_service_api_v2_submit_message(
            client=999999, payload=EXAMPLE_INPUT, tags=tags
        )
        assert missing_client.status_code == 404

    @rule(payload=st.text(alphabet="payload012345", min_size=1, max_size=12))
    def update_message(self, payload):
        uid = self.message_ids[0]
        response = self.api.put_service_api_v2_adjust_message(
            uid, {"payload": payload, "tags": "changed"}
        )
        assert response.status_code == 200
        assert response.json()["payload"] == payload

        launched = self.api.put_service_api_v2_adjust_message(uid, {"launched": 123})
        assert launched.status_code == 200
        bad_launched = self.api.put_service_api_v2_adjust_message(
            uid, {"launched": "later"}
        )
        assert bad_launched.status_code == 400

        missing = self.api.put_service_api_v2_adjust_message(
            999999, {"tags": "missing"}
        )
        assert missing.status_code == 404

    @rule()
    def read_outputs_and_report(self):
        message_uid = self.message_ids[0]
        response = self.api.get_service_api_v2_collect_output(message_uid)
        assert response.status_code == 200
        assert response.json()
        output = response.json()[0]
        filtered_outputs = self.api.get_service_api_v2_collect_output(
            message_uid,
            uid=output["uid"],
            created=output["created"],
            response=output["response"],
            stage=output["stage"],
            failure=output["failure"],
            cache_hit=output["cache_hit"],
        )
        assert filtered_outputs.status_code == 200
        assert len(filtered_outputs.json()) == 1

        filtered = self.api.get_service_api_v2_collect_output(
            message_uid, stage="not-a-real-stage", cache_hit=1
        )
        assert filtered.status_code == 200
        assert filtered.json() == []

        report = self.api.get_service_api_v2_collect_report()
        assert report.status_code == 200

    @rule()
    def check_required_headers(self):
        missing_content_type = self.api.post_service_api_v2_submit_client(
            "platform", "agent", headers={"Accept-Language": "ru-RU"}
        )
        assert missing_content_type.status_code == 415

        missing_language = self.api.get_service_api_v2_collect_client(headers={})
        assert missing_language.status_code == 406

        invalid_language = self.api.get_service_api_v2_collect_report(
            headers={"Accept-Language": "en-US"}
        )
        assert invalid_language.status_code == 406

        # With both headers missing, Content-Type has priority for POST.
        both_missing = self.api.post_service_api_v2_submit_client(
            "platform", "agent", headers={}
        )
        assert both_missing.status_code == 415

        docs = self.api._request("GET", "/docs", headers={})
        assert docs.status_code == 200

    @rule()
    def execute_cli_success_and_failure(self):
        self.app.state.test_mode = False
        success = self.api.post_service_api_v2_submit_message(
            client=self.client_ids[0], payload=EXAMPLE_INPUT, tags="real-cli"
        )
        assert success.status_code == 200
        self.message_ids.append(success.json()["uid"])
        outputs = self.api.get_service_api_v2_collect_output(success.json()["uid"])
        assert outputs.status_code == 200
        assert outputs.json()[0]["stage"] == "completed"
        assert len(outputs.json()[0]["response"]) == 32

        failure = self.api.post_service_api_v2_submit_message(
            client=self.client_ids[0], payload=MISSING_INPUT, tags="missing-file"
        )
        assert failure.status_code == 200
        self.message_ids.append(failure.json()["uid"])
        outputs = self.api.get_service_api_v2_collect_output(failure.json()["uid"])
        assert outputs.status_code == 200
        assert outputs.json()[0]["stage"] == "failed"
        assert outputs.json()[0]["failure"]
        self.app.state.test_mode = True

    @rule()
    def test_invalid_update_body(self):
        message_uid = self.message_ids[0]
        response = self.api.put_service_api_v2_adjust_message(
            message_uid, ["not", "an", "object"]
        )
        assert response.status_code == 400

        response = self.api.put_service_api_v2_adjust_client(
            self.client_ids[0], {"unknown": "field"}
        )
        assert response.status_code == 400

        response = self.api.put_service_api_v2_adjust_message(
            message_uid, {"unknown": "field"}
        )
        assert response.status_code == 400

        response = self.api._request(
            "PUT",
            f"/service/api/v2/adjust-message/{message_uid}",
            headers={"Content-Type": "text/json", "Accept-Language": "ru-RU"},
        )
        assert response.status_code == 400

    @rule()
    def report_excludes_old_clients(self):
        uid = self.client_ids[0]
        response = self.api.put_service_api_v2_adjust_client(uid, {"created": 0})
        assert response.status_code == 200
        report = self.api.get_service_api_v2_collect_report()
        assert report.status_code == 200

        message_uid = self.message_ids[0]
        saved_client = self.app.state.store.messages[message_uid]["client"]
        self.app.state.store.messages[message_uid]["client"] = 999999
        report = self.api.get_service_api_v2_collect_report()
        assert report.status_code == 200
        self.app.state.store.messages[message_uid]["client"] = saved_client


TestApiStateMachine = ApiStateMachine.TestCase
TestApiStateMachine.settings = settings(
    max_examples=10,
    stateful_step_count=12,
    deadline=None,
)
