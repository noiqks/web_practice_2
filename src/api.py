import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = Path(__file__).resolve().parent / "md5_hasher.py"


class MemoryStore:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clients = {}
        self.messages = {}
        self.outputs = {}
        self.next_client_uid = 1
        self.next_message_uid = 1
        self.next_output_uid = 1

    def add_client(self, platform, user_agent):
        uid = self.next_client_uid
        self.next_client_uid += 1
        client = {
            "uid": uid,
            "created": int(time.time()),
            "platform": platform,
            "user_agent": user_agent,
        }
        self.clients[uid] = client
        return client.copy()

    def add_message(self, payload, client, tags, stage, launched):
        uid = self.next_message_uid
        self.next_message_uid += 1
        message = {
            "uid": uid,
            "created": int(time.time()),
            "payload": payload,
            "client": client,
            "tags": tags,
            "stage": stage,
            "launched": launched,
        }
        self.messages[uid] = message
        return message.copy()

    def add_output(self, message, response, stage, failure, cache_hit=0):
        uid = self.next_output_uid
        self.next_output_uid += 1
        output = {
            "uid": uid,
            "created": int(time.time()),
            "response": response,
            "stage": stage,
            "failure": failure,
            "message": message,
            "cache_hit": cache_hit,
        }
        self.outputs[uid] = output
        return output.copy()


def run_md5_cli(input_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / "md5-result.txt"
        command = [
            sys.executable,
            str(CLI_PATH),
            str(input_path),
            str(output_path),
        ]
        subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return output_path.read_text(encoding="utf-8").strip()


def execute_message_task(store, message_uid, output_uid, input_path):
    try:
        response = run_md5_cli(input_path)
        stage = "completed"
        failure = ""
    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as error:
        response = ""
        stage = "failed"
        failure = str(error)

    store.messages[message_uid]["stage"] = stage
    store.outputs[output_uid].update(
        {
            "response": response,
            "stage": stage,
            "failure": failure,
        }
    )


async def read_json_object(request):
    try:
        raw_body = await request.body()
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail="JSON body must be an object",
        )

    return data


def apply_filters(items, filters):
    result = items

    for field, value in filters.items():
        if value is not None:
            result = [item for item in result if item[field] == value]

    return result


def register_middleware(app):
    @app.middleware("http")
    async def check_headers(request: Request, call_next):
        if not request.url.path.startswith("/service/api/v2/"):
            return await call_next(request)

        if (
            request.method in {"POST", "PUT", "PATCH"}
            and request.headers.get("content-type") != "text/json"
        ):
            return JSONResponse(
                status_code=415,
                content={"detail": "Content-Type must be text/json"},
            )

        if request.headers.get("accept-language") != "ru-RU":
            return JSONResponse(
                status_code=406,
                content={"detail": "Accept-Language must be ru-RU"},
            )

        return await call_next(request)


def add_client(app, platform, user_agent):
    return app.state.store.add_client(platform, user_agent)


def get_clients(app, filters):
    clients = list(app.state.store.clients.values())
    return apply_filters(clients, filters)


def update_client(app, uid, body):
    client = app.state.store.clients.get(uid)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    allowed_fields = {"platform", "user_agent", "created"}

    for field, value in body.items():
        if field not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail="Unsupported client field",
            )

        if field == "created" and not isinstance(value, int):
            raise HTTPException(
                status_code=400,
                detail="created must be an integer",
            )

        if field != "created" and not isinstance(value, str):
            raise HTTPException(
                status_code=400,
                detail=f"{field} must be a string",
            )

        client[field] = value

    return client.copy()


async def adjust_client(app, uid, request):
    body = await read_json_object(request)
    return update_client(app, uid, body)


def register_client_routes(app):
    @app.post("/service/api/v2/submit-client")
    async def submit_client(platform: str, user_agent: str):
        return add_client(app, platform, user_agent)

    @app.get("/service/api/v2/collect-client")
    async def collect_client(
        uid: int | None = None,
        created: int | None = None,
        platform: str | None = None,
        user_agent: str | None = None,
    ):
        filters = {
            "uid": uid,
            "created": created,
            "platform": platform,
            "user_agent": user_agent,
        }
        return get_clients(app, filters)

    @app.put("/service/api/v2/adjust-client/{uid}")
    async def adjust_client_route(uid: int, request: Request):
        return await adjust_client(app, uid, request)


def add_test_message(app, client, payload, tags):
    message = app.state.store.add_message(
        payload=payload,
        client=client,
        tags=tags,
        stage="skipped",
        launched=0,
    )
    app.state.store.add_output(
        message=message["uid"],
        response="Task not executed in test mode",
        stage="skipped",
        failure="",
    )
    return message


def add_queued_message(app, background_tasks, client, payload, tags):
    launched = int(time.time())
    message = app.state.store.add_message(
        payload=payload,
        client=client,
        tags=tags,
        stage="queued",
        launched=launched,
    )
    output = app.state.store.add_output(
        message=message["uid"],
        response="",
        stage="queued",
        failure="",
    )
    background_tasks.add_task(
        execute_message_task,
        app.state.store,
        message["uid"],
        output["uid"],
        payload,
    )
    return message


def create_message(app, background_tasks, client, payload, tags):
    if client not in app.state.store.clients:
        raise HTTPException(status_code=404, detail="Client not found")

    if app.state.test_mode:
        return add_test_message(app, client, payload, tags)

    return add_queued_message(
        app,
        background_tasks,
        client,
        payload,
        tags,
    )


def get_messages(app, client, filters):
    messages = [
        item for item in app.state.store.messages.values() if item["client"] == client
    ]
    return apply_filters(messages, filters)


def update_message(app, uid, body):
    message = app.state.store.messages.get(uid)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    allowed_fields = {"payload", "tags", "stage", "launched"}

    for field, value in body.items():
        if field not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail="Unsupported message field",
            )

        if field == "launched":
            if not isinstance(value, int):
                raise HTTPException(
                    status_code=400,
                    detail="launched must be an integer",
                )
        elif not isinstance(value, str):
            raise HTTPException(
                status_code=400,
                detail=f"{field} must be a string",
            )

        message[field] = value

    return message.copy()


async def adjust_message(app, uid, request):
    body = await read_json_object(request)
    return update_message(app, uid, body)


def register_message_routes(app):
    @app.post("/service/api/v2/submit-message")
    async def submit_message(
        background_tasks: BackgroundTasks,
        client: int,
        payload: str,
        tags: str = "",
    ):
        return create_message(
            app,
            background_tasks,
            client,
            payload,
            tags,
        )

    @app.get("/service/api/v2/collect-message/{client}")
    async def collect_message(
        client: int,
        uid: int | None = None,
        created: int | None = None,
        payload: str | None = None,
        tags: str | None = None,
        stage: str | None = None,
        launched: int | None = None,
    ):
        filters = {
            "uid": uid,
            "created": created,
            "payload": payload,
            "tags": tags,
            "stage": stage,
            "launched": launched,
        }
        return get_messages(app, client, filters)

    @app.put("/service/api/v2/adjust-message/{uid}")
    async def adjust_message_route(uid: int, request: Request):
        return await adjust_message(app, uid, request)


def get_outputs(app, message, filters):
    outputs = [
        item for item in app.state.store.outputs.values() if item["message"] == message
    ]
    return apply_filters(outputs, filters)


def get_report(app):
    cutoff = int(time.time()) - 7 * 60
    report = []

    for message in app.state.store.messages.values():
        client = app.state.store.clients.get(message["client"])
        if client is not None and client["created"] >= cutoff:
            report.append(
                {
                    "user_agent": client["user_agent"],
                    "payload": message["payload"],
                    "tags": message["tags"],
                }
            )

    return report


def register_output_routes(app):
    @app.get("/service/api/v2/collect-output/{message}")
    async def collect_output(
        message: int,
        uid: int | None = None,
        created: int | None = None,
        response: str | None = None,
        stage: str | None = None,
        failure: str | None = None,
        cache_hit: int | None = None,
    ):
        filters = {
            "uid": uid,
            "created": created,
            "response": response,
            "stage": stage,
            "failure": failure,
            "cache_hit": cache_hit,
        }
        return get_outputs(app, message, filters)

    @app.get("/service/api/v2/collect-report")
    async def collect_report():
        return get_report(app)


def create_app(test_mode=None):
    app = FastAPI(title="MD5 Task API", version="2.0")
    app.state.store = MemoryStore()

    if test_mode is None:
        app.state.test_mode = os.getenv("MD5_TEST_MODE", "0") == "1"
    else:
        app.state.test_mode = test_mode

    register_middleware(app)
    register_client_routes(app)
    register_message_routes(app)
    register_output_routes(app)

    return app


app = create_app()
