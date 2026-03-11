import logging
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from server.src.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

SKIP_PREFIXES = ("/health", "/ws/", "/docs", "/openapi.json", "/redoc")
SKIP_METHODS = {"GET", "OPTIONS", "HEAD"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        method = request.method

        if method in SKIP_METHODS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        body_text = None
        try:
            raw = await request.body()
            if raw:
                body_text = raw.decode("utf-8", errors="replace")[:1000]
        except Exception:
            pass

        user_id = None
        username = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from server.src.services.auth_service import decode_token
                payload = decode_token(auth_header[7:])
                user_id = payload.get("sub")
                username = payload.get("username")
            except Exception:
                pass

        response = await call_next(request)

        try:
            await AuditLog(
                user_id=user_id,
                username=username,
                method=method,
                path=path,
                status_code=response.status_code,
                request_body=body_text,
                timestamp=datetime.now(timezone.utc),
                ip_address=request.client.host if request.client else None,
            ).insert()
        except Exception as e:
            logger.warning("Audit log write failed: %s", e)

        return response
