from fastapi import FastAPI
from .database import engine, Base
from .routes import router
import uvicorn

app = FastAPI(title="BW Backend Control API")

# Include the router
app.include_router(router)

@app.on_event("startup")
async def startup():
    # Create tables automatically on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
async def root():
    return {"message": "Welcome to BW Backend Control API"}

if __name__ == "__main__":
    uvicorn.run("control.main:app", host="0.0.0.0", port=8008, reload=True)
