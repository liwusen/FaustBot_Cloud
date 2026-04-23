from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .config import CloudConfig, load_config
from .service import CloudInferenceService, CloudServiceError, TtsRequest
from .storage import CloudStorage
from .billing import POINT_SCALE


class TtsPayload(BaseModel):
    refer_hash: str = Field(default="")
    prompt_text: str = Field(default="")
    prompt_language: str = Field(default="")
    text: str
    text_language: str = Field(default="zh")


def _extract_service_key(authorization: str | None, x_service_key: str | None) -> str:
    bearer = str(authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    return str(x_service_key or bearer).strip()


def _extract_root_key(authorization: str | None, x_root_key: str | None) -> str:
    bearer = str(authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    return str(x_root_key or bearer).strip()


def create_app(config: CloudConfig | None = None, storage: CloudStorage | None = None) -> FastAPI:
    runtime_config = config or load_config()
    runtime_storage = storage or CloudStorage(runtime_config.database_file)
    runtime_storage.initialize()
    service = CloudInferenceService(runtime_config, runtime_storage)
    # ephemeral state store for OAuth CSRF protection
    app_state_oauth = {}

    app = FastAPI(title="FaustBot Cloud Inference Server")
    app.state.cloud_config = runtime_config
    app.state.cloud_storage = runtime_storage
    app.state.cloud_service = service
    app.state.oauth_state = app_state_oauth
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_config.cors_allow_origins or ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(CloudServiceError)
    async def handle_cloud_error(_: Request, exc: CloudServiceError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "code": exc.code})

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "host": runtime_config.host,
            "port": runtime_config.port,
            "database_path": str(runtime_config.database_file),
            "reference_dir": str(runtime_config.reference_root),
        }

    @app.post("/v1/references")
    async def upload_reference(
        file: UploadFile = File(...),
        prompt_text: str = Form(...),
        prompt_language: str = Form("zh"),
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> dict:
        audio_bytes = await file.read()
        return service.upload_reference(
            _extract_service_key(authorization, x_service_key),
            file.filename or "reference.wav",
            audio_bytes,
            prompt_text,
            prompt_language,
            file.content_type or "audio/wav",
        )

    @app.get("/v1/references/{refer_hash}")
    async def get_reference(
        refer_hash: str,
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> dict:
        return service.get_reference(_extract_service_key(authorization, x_service_key), refer_hash)

    @app.get("/v1/references/by-signature/{signature}")
    async def get_reference_by_signature(
        signature: str,
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> dict:
        result = service.find_reference_by_signature(_extract_service_key(authorization, x_service_key), signature)
        if result is None:
            raise CloudServiceError("未找到对应的参考音频", status_code=404, code="reference_not_found")
        return result

    @app.post("/v1/tts")
    async def synthesize_tts(
        payload: TtsPayload,
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> Response:
        print(f"Received TTS POST request with payload={payload.json()}")
        audio_bytes, content_type, usage = service.synthesize_tts(
            _extract_service_key(authorization, x_service_key),
            TtsRequest(**payload.model_dump()),
        )
        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "X-Usage-Hourly-Points": str(usage["hourly_points"]),
                "X-Usage-Daily-Points": str(usage["daily_points"]),
            },
        )

    @app.get("/v1/tts")
    async def synthesize_tts_get(
        refer_hash: str = Query(default=""),
        prompt_text: str = Query(default=""),
        prompt_language: str = Query(default=""),
        text: str = Query(...),
        text_language: str = Query(default="zh"),
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> Response:
        print(f"Received TTS GET request with refer_hash={refer_hash}, prompt_text={prompt_text}, prompt_language={prompt_language}, text={text}, text_language={text_language}")
        audio_bytes, content_type, usage = service.synthesize_tts(
            _extract_service_key(authorization, x_service_key),
            TtsRequest(
                refer_hash=refer_hash,
                prompt_text=prompt_text,
                prompt_language=prompt_language,
                text=text,
                text_language=text_language,
            ),
        )
        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "X-Usage-Hourly-Points": str(usage["hourly_points"]),
                "X-Usage-Daily-Points": str(usage["daily_points"]),
            },
        )

    @app.post("/v1/asr")
    async def transcribe_asr(
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
        x_service_key: str | None = Header(default=None),
    ) -> dict:
        audio_bytes = await file.read()
        return service.transcribe_asr(
            _extract_service_key(authorization, x_service_key),
            file.filename or "audio.wav",
            audio_bytes,
            file.content_type or "audio/wav",
        )


    @app.get("/oauth-login")
    async def oauth_login(request: Request):
        cfg: CloudConfig = app.state.cloud_config
        if not getattr(cfg, "github_oauth_enabled", False):
            raise CloudServiceError("GitHub OAuth 未启用", status_code=404, code="oauth_not_enabled")
        from . import github_oauth

        state = github_oauth.generate_state()
        url_state = github_oauth.build_authorize_url(cfg.github_oauth_client_id, cfg.github_oauth_callback_url, cfg.github_oauth_scopes, state)
        # build_authorize_url returns (url, state)
        if isinstance(url_state, tuple):
            authorize_url, _ = url_state
        else:
            authorize_url = url_state
        # store ephemeral state
        app.state.oauth_state[state] = True
        return RedirectResponse(authorize_url)

    @app.get("/oauth/callback")
    async def oauth_callback(code: str | None = Query(default=None), state: str | None = Query(default=None)):
        cfg: CloudConfig = app.state.cloud_config
        if not getattr(cfg, "github_oauth_enabled", False):
            raise CloudServiceError("GitHub OAuth 未启用", status_code=404, code="oauth_not_enabled")
        if not code or not state:
            raise CloudServiceError("缺少 code 或 state", status_code=400, code="invalid_oauth_callback")
        # validate state
        if not app.state.oauth_state.pop(state, None):
            raise CloudServiceError("无效或过期的 state", status_code=400, code="invalid_state")
        from . import github_oauth

        # exchange code
        try:
            access_token = github_oauth.exchange_code_for_token(code, cfg.github_oauth_client_id, cfg.github_oauth_client_secret, cfg.github_oauth_callback_url, cfg.github_api_base)
            gh_user = github_oauth.get_github_user(access_token, cfg.github_api_base)
        except Exception as exc:
            raise CloudServiceError("GitHub 授权失败", status_code=400, code="oauth_exchange_failed")

        github_id = str(gh_user.get("id"))
        github_login = str(gh_user.get("login") or "")
        github_email = str(gh_user.get("email") or "")

        record = app.state.cloud_storage.create_or_get_service_key_for_github(github_id, github_login, github_email)
        # return a simple JSON with the internal key
        return {"service_key": record.service_key, "name": record.name, "note": record.note, "created_at": record.created_at}

    def _require_root_key(authorization: str | None, x_root_key: str | None) -> None:
        root_key = _extract_root_key(authorization, x_root_key)
        configured_root = str(getattr(app.state.cloud_config, "root_key", "") or "").strip()
        if not configured_root:
            raise CloudServiceError("未配置 ROOT key", status_code=403, code="root_key_not_configured")
        if not root_key or root_key != configured_root:
            raise CloudServiceError("ROOT key 无效", status_code=401, code="invalid_root_key")

    @app.post("/v1/admin/keys")
    async def create_service_key(
        name: str = Form(default=""),
        note: str = Form(default=""),
        authorization: str | None = Header(default=None),
        x_root_key: str | None = Header(default=None),
    ) -> dict:
        _require_root_key(authorization, x_root_key)
        record = app.state.cloud_storage.create_service_key(name=name, note=note)
        return {
            "service_key": record.service_key,
            "name": record.name,
            "note": record.note,
            "enabled": record.enabled,
            "created_at": record.created_at,
        }

    @app.get("/v1/admin/keys")
    async def admin_list_keys(
        authorization: str | None = Header(default=None),
        x_root_key: str | None = Header(default=None),
    ) -> list[dict]:
        _require_root_key(authorization, x_root_key)
        return [
            {
                "service_key": r.service_key,
                "name": r.name,
                "note": r.note,
                "enabled": r.enabled,
                "created_at": r.created_at,
            }
            for r in app.state.cloud_storage.list_service_keys()
        ]

    @app.post("/v1/admin/keys/{service_key}/enable")
    async def admin_enable_key(
        service_key: str,
        authorization: str | None = Header(default=None),
        x_root_key: str | None = Header(default=None),
    ) -> dict:
        _require_root_key(authorization, x_root_key)
        updated = app.state.cloud_storage.set_service_key_enabled(service_key, True)
        return {"updated": updated, "service_key": service_key, "enabled": True}

    @app.post("/v1/admin/keys/{service_key}/disable")
    async def admin_disable_key(
        service_key: str,
        authorization: str | None = Header(default=None),
        x_root_key: str | None = Header(default=None),
    ) -> dict:
        _require_root_key(authorization, x_root_key)
        updated = app.state.cloud_storage.set_service_key_enabled(service_key, False)
        return {"updated": updated, "service_key": service_key, "enabled": False}

    @app.post("/v1/admin/keys/{service_key}/reset-usage")
    async def admin_reset_usage(
        service_key: str,
        authorization: str | None = Header(default=None),
        x_root_key: str | None = Header(default=None),
    ) -> dict:
        _require_root_key(authorization, x_root_key)
        deleted_rows = app.state.cloud_storage.reset_usage(service_key)
        return {"deleted_rows": deleted_rows, "service_key": service_key}

    @app.get("/v1/keys/{service_key}/usage")
    async def get_key_usage(service_key: str, authorization: str | None = Header(default=None), x_service_key: str | None = Header(default=None)):
        # allow admin-style access if provided key matches or simply require same key in header
        header_key = _extract_service_key(authorization, x_service_key)
        # require that caller presents the same key (privacy) or present any valid key (admin CLI can use storage directly)
        if not header_key or header_key != service_key:
            # still allow if header_key is a valid enabled key and different from target
            try:
                app.state.cloud_service.authenticate(header_key)
            except CloudServiceError:
                raise CloudServiceError("需要有效的 Service Key 来查询用量", status_code=401, code="missing_service_key")
        usage = app.state.cloud_storage.get_usage_snapshot(
            service_key,
            hourly_limit_units=app.state.cloud_config.hourly_limit_points * POINT_SCALE,
            daily_limit_units=app.state.cloud_config.daily_limit_points * POINT_SCALE,
        )
        return usage.to_dict()

    return app


app = create_app()