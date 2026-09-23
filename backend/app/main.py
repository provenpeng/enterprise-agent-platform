from fastapi import FastAPI

from app.api.router import api_router


app = FastAPI(title="Enterprise Agent Platform")
app.include_router(api_router)
