from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class OpenAIError(Exception):
    def __init__(self, status: int, code: str, message: str, typ: str = "invalid_request_error"):
        self.status = status
        self.code = code
        self.message = message
        self.typ = typ


def register_error_handler(app: FastAPI) -> None:
    @app.exception_handler(OpenAIError)
    async def _handler(request: Request, exc: OpenAIError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"message": exc.message, "type": exc.typ, "code": exc.code}},
        )
