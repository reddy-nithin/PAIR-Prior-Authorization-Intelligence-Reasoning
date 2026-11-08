"""FastAPI app factory: settings, error envelope, CORS for the local web app, log redaction (Phase 4 T7).

Run it with ``make api`` (uvicorn on 127.0.0.1:8000). It serves only the laptop:
CORS allows the local Next.js origin and nothing else, and uploads never leave
memory (see ``routes``). Every error is ``{"error": {"code", "message"}}`` and no
message quotes case content.
"""

import logging
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pair.api.routes import ApiError, router
from pair.ui.demo_build import CACHE
from pair.ui.privacy import install_log_redaction
from pair.ui.runner import Runner

logger = logging.getLogger(__name__)

LOCAL_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
_LOCAL = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")
MAX_BODY_BYTES = 50_000_000  # base64 of a denial + records under the 20 MB per-file cap
# Not "uvicorn.access": its formatter unpacks 5 args, which the filter clears; `make api` runs --no-access-log.
SERVER_LOGGERS = ("uvicorn", "uvicorn.error")


class ApiConfigError(ValueError):
    """The API settings are invalid."""


@dataclass(frozen=True)
class ApiSettings:
    """What the app serves: the demo cache folder, an optional live runner, and its limits."""

    cache_dir: Path = CACHE
    runner: Runner | None = None
    origins: tuple[str, ...] = LOCAL_ORIGINS
    max_body_bytes: int = MAX_BODY_BYTES
    redact_logs: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ApiSettings":
        """Settings from ``PAIR_DEMO_CACHE``, ``PAIR_WEB_ORIGINS`` (comma list), ``PAIR_REDACT_LOGS`` and ``PAIR_LIVE``.

        Raises:
            LLMConfigError, VerifierConfigError: If ``PAIR_LIVE=1`` and the model settings are invalid.
        """
        origins = tuple(o.strip() for o in env.get("PAIR_WEB_ORIGINS", "").split(",") if o.strip()) or LOCAL_ORIGINS
        return cls(
            cache_dir=Path(env.get("PAIR_DEMO_CACHE", str(CACHE))),
            runner=_live_runner(env) if env.get("PAIR_LIVE") == "1" else None,
            origins=origins,
            redact_logs=env.get("PAIR_REDACT_LOGS", "1") != "0",
        )


def _live_runner(env: Mapping[str, str]) -> Runner:  # pragma: no cover - needs the lab models
    """The real runner: the configured drafter (lab E4B by default), LangExtract and the verifier."""
    import langextract as lx

    from pair.llm import LLMConfig, make_client
    from pair.verify.nli import VerifierConfig, make_verifier

    config = LLMConfig.from_env(dict(env))
    return Runner(make_client(config), config, lx.extract, make_verifier(VerifierConfig.from_env(dict(env))))


def _envelope(status: int, code: str, message: str) -> JSONResponse:
    """The one error shape."""
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _install_handlers(app: FastAPI) -> None:
    """Map every error to the envelope."""

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _envelope(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(400, "bad_request", f"invalid request ({len(exc.errors())} problem(s))")


def create_app(settings: ApiSettings) -> FastAPI:
    """Build the app.

    Raises:
        ApiConfigError: If an origin isn't a local http origin.
        PrivacyError: If log redaction is on and the spaCy model is missing.
    """
    if bad := [origin for origin in settings.origins if not _LOCAL.match(origin)]:
        raise ApiConfigError(f"CORS origins must be localhost or 127.0.0.1 over http, not {', '.join(bad)}")
    if settings.redact_logs:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
        install_log_redaction()
        for name in SERVER_LOGGERS:
            install_log_redaction(logging.getLogger(name))
    app = FastAPI(title="PAIR demo API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.live_lock = threading.Lock()
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], expose_headers=["X-Run-Seconds", "Content-Disposition"])  # fmt: skip
    _install_handlers(app)
    app.include_router(router)
    logger.info("demo API: cache %s, live %s", settings.cache_dir, "on" if settings.runner else "off")
    return app


def app_from_env() -> FastAPI:  # pragma: no cover - uvicorn entry point (`make api`)
    """The app configured from the environment."""
    return create_app(ApiSettings.from_env(os.environ))
