from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.services.errors import (
    Conflict,
    NotFound,
    PayloadTooLarge,
    ServiceError,
    UnsupportedMedia,
)


app = FastAPI(title="Enterprise Agent Platform")


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    if isinstance(exc, NotFound):
        status_code = 404
    elif isinstance(exc, Conflict):
        status_code = 409
    elif isinstance(exc, PayloadTooLarge):
        status_code = 413
    elif isinstance(exc, UnsupportedMedia):
        status_code = 415
    else:
        status_code = 400
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


app.include_router(api_router)
