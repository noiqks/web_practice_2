import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from src.database import create_database
from src.models import Base
from src.store import SqliteStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = Path(__file__).resolve().parent / "md5_hasher.py"

CLI_TIMEOUT_SECONDS = 30
REPORT_WINDOW_SECONDS = 7 * 60
API_PREFIX = "/service/api/v2/"
JSON_CONTENT_TYPE = "text/json"
REQUIRED_LANGUAGE = "ru-RU"

STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"
STAGE_QUEUED = "queued"

TEST_MODE_ENV = "MD5_TEST_MODE"
TEST_MODE_ON = "1"

HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_NOT_ACCEPTABLE = 406
HTTP_UNSUPPORTED_MEDIA_TYPE = 415

DOCS_HTML = (
    "<!DOCTYPE html>\n"
    "<html>\n"
    "<head>\n"
    "    <title>MD5 Task API</title>\n"
    '    <link rel="stylesheet"\n'
    '          href="https://cdn.jsdelivr.net/npm/'
    'swagger-ui-dist@5/swagger-ui.css">\n'
    "</head>\n"
    "<body>\n"
    '    <div id="swagger-ui"></div>\n'
    '    <script src="https://cdn.jsdelivr.net/npm/'
    'swagger-ui-dist@5/swagger-ui-bundle.js"></script>\n'
    "    <script>\n"
    "        const ui = SwaggerUIBundle({\n"
    '            url: "/openapi.json",\n'
    '            dom_id: "#swagger-ui",\n'
    "            presets: [\n"
    "                SwaggerUIBundle.presets.apis,\n"
    "                SwaggerUIBundle.SwaggerUIStandalonePreset\n"
    "            ],\n"
    '            layout: "BaseLayout",\n'
    "            requestInterceptor: (request) => {\n"
    '                if (request.url.includes('
    '"/service/api/v2/")) {\n'
    "                    request.headers = "
    "request.headers || {};\n"
    '                    request.headers["Accept-Language"] '
    '= "ru-RU";\n'
    '                    if (["POST", "PUT", "PATCH"].includes(\n'
    "                        (request.method || "
    '"GET").toUpperCase()\n'
    "                    )) {\n"
    '                        request.headers["Content-Type"] '
    '= "text/json";\n'
    "                    }\n"
    "                }\n"
    "                return request;\n"
    "            }\n"
    "        });\n"
    "    </script>\n"
    "</body>\n"
    "</html>\n"
)


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
            timeout=CLI_TIMEOUT_SECONDS,
            check=True,
        )

        return output_path.read_text(encoding="utf-8").strip()


def execute_message_task(store, message_uid, output_uid, input_path):
    try:
        response = run_md5_cli(input_path)
        stage = STAGE_COMPLETED
        failure = ""
    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as error:
        response = ""
        stage = STAGE_FAILED
        failure = str(error)

    store.update_message(message_uid, {"stage": stage})

    store.update_output(
        output_uid,
        {
            "response": response,
            "stage": stage,
            "failure": failure,
        },
    )


async def read_json_object(request):
    try:
        raw_body = await request.body()
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=HTTP_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=HTTP_BAD_REQUEST,
            detail="JSON body must be an object",
        )

    return data


def register_middleware(app):
    @app.middleware("http")
    async def check_headers(request: Request, call_next):
        if not request.url.path.startswith(API_PREFIX):
            return await call_next(request)

        if (
            request.method in {"POST", "PUT", "PATCH"}
            and request.headers.get("content-type") != JSON_CONTENT_TYPE
        ):
            return JSONResponse(
                status_code=HTTP_UNSUPPORTED_MEDIA_TYPE,
                content={"detail": "Content-Type must be text/json"},
            )

        if (
            request.headers.get("accept-language")
            != REQUIRED_LANGUAGE
        ):
            return JSONResponse(
                status_code=HTTP_NOT_ACCEPTABLE,
                content={"detail": "Accept-Language must be ru-RU"},
            )

        return await call_next(request)


def register_submit_client_route(app):
    @app.post("/service/api/v2/submit-client")
    async def submit_client(platform: str, user_agent: str):
        return app.state.store.add_client(platform, user_agent)


def register_collect_client_route(app):
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

        return app.state.store.get_clients(filters)


def validate_client_values(body, allowed_fields):
    for field, value in body.items():
        if field not in allowed_fields:
            raise HTTPException(
                status_code=HTTP_BAD_REQUEST,
                detail="Unsupported client field",
            )

        if field == "created":
            if not isinstance(value, int):
                raise HTTPException(
                    status_code=HTTP_BAD_REQUEST,
                    detail="created must be an integer",
                )
        elif not isinstance(value, str):
            raise HTTPException(
                status_code=HTTP_BAD_REQUEST,
                detail=f"{field} must be a string",
            )


def register_adjust_client_route(app):
    @app.put("/service/api/v2/adjust-client/{uid}")
    async def adjust_client(uid: int, request: Request):
        body = await read_json_object(request)

        allowed_fields = {
            "platform",
            "user_agent",
            "created",
        }

        validate_client_values(body, allowed_fields)

        client = app.state.store.update_client(uid, body)

        if client is None:
            raise HTTPException(
                status_code=HTTP_NOT_FOUND,
                detail="Client not found",
            )

        return client


def register_client_routes(app):
    register_submit_client_route(app)
    register_collect_client_route(app)
    register_adjust_client_route(app)


def register_submit_message_route(app):
    @app.post("/service/api/v2/submit-message")
    async def submit_message(
        background_tasks: BackgroundTasks,
        client: int,
        payload: str,
        tags: str = "",
    ):
        if app.state.store.get_client(client) is None:
            raise HTTPException(
                status_code=HTTP_NOT_FOUND,
                detail="Client not found",
            )

        if app.state.test_mode:
            return create_test_message(
                app.state.store,
                payload,
                client,
                tags,
            )

        return create_real_message(
            app,
            background_tasks,
            payload,
            client,
            tags,
        )


def register_collect_message_route(app):
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

        return app.state.store.get_messages(client, filters)


def validate_message_values(body, allowed_fields):
    for field, value in body.items():
        if field not in allowed_fields:
            raise HTTPException(
                status_code=HTTP_BAD_REQUEST,
                detail="Unsupported message field",
            )

        if field == "launched":
            if not isinstance(value, int):
                raise HTTPException(
                    status_code=HTTP_BAD_REQUEST,
                    detail="launched must be an integer",
                )
        elif not isinstance(value, str):
            raise HTTPException(
                status_code=HTTP_BAD_REQUEST,
                detail=f"{field} must be a string",
            )


def register_adjust_message_route(app):
    @app.put("/service/api/v2/adjust-message/{uid}")
    async def adjust_message(uid: int, request: Request):
        body = await read_json_object(request)

        allowed_fields = {
            "payload",
            "tags",
            "stage",
            "launched",
        }

        validate_message_values(body, allowed_fields)

        message = app.state.store.update_message(uid, body)

        if message is None:
            raise HTTPException(
                status_code=HTTP_NOT_FOUND,
                detail="Message not found",
            )

        return message


def register_message_routes(app):
    register_submit_message_route(app)
    register_collect_message_route(app)
    register_adjust_message_route(app)


def create_test_message(store, payload, client, tags):
    message = store.add_message(
        payload=payload,
        client=client,
        tags=tags,
        stage=STAGE_SKIPPED,
        launched=0,
    )

    store.add_output(
        message=message["uid"],
        response="Task not executed in test mode",
        stage=STAGE_SKIPPED,
        failure="",
    )

    return message


def create_real_message(
    app,
    background_tasks,
    payload,
    client,
    tags,
):
    launched = int(time.time())

    message = app.state.store.add_message(
        payload=payload,
        client=client,
        tags=tags,
        stage=STAGE_QUEUED,
        launched=launched,
    )

    output = app.state.store.add_output(
        message=message["uid"],
        response="",
        stage=STAGE_QUEUED,
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


def register_collect_output_route(app):
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

        return app.state.store.get_outputs(message, filters)


def register_collect_report_route(app):
    @app.get("/service/api/v2/collect-report")
    async def collect_report():
        cutoff = int(time.time()) - REPORT_WINDOW_SECONDS

        return app.state.store.get_report(cutoff)


def register_output_routes(app):
    register_collect_output_route(app)
    register_collect_report_route(app)


def register_custom_docs(app):
    @app.get("/docs", include_in_schema=False)
    async def custom_docs():
        return HTMLResponse(DOCS_HTML)


def custom_openapi(app):
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )

    for path in [
        "/service/api/v2/adjust-client/{uid}",
        "/service/api/v2/adjust-message/{uid}",
    ]:
        operation = openapi_schema["paths"][path]["put"]

        operation["requestBody"] = {
            "required": True,
            "content": {
                JSON_CONTENT_TYPE: {
                    "schema": {
                        "type": "object",
                        "additionalProperties": True,
                    }
                }
            },
        }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def create_app(
    test_mode=None,
    database_url="sqlite:///md5_tasks.db",
):
    app = FastAPI(
        title="MD5 Task API",
        version="3.0",
        docs_url=None,
    )

    engine, session_factory = create_database(database_url)

    Base.metadata.create_all(engine)

    app.state.engine = engine
    app.state.store = SqliteStore(session_factory)

    if test_mode is None:
        app.state.test_mode = (
            os.getenv(TEST_MODE_ENV, "0") == TEST_MODE_ON
        )
    else:
        app.state.test_mode = test_mode

    register_middleware(app)
    register_client_routes(app)
    register_message_routes(app)
    register_output_routes(app)

    app.openapi = lambda: custom_openapi(app)

    register_custom_docs(app)

    return app


app = create_app()
