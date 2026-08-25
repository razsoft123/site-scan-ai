from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def get_health():
    return {
        "status": "Server is running",
        "time": "time"
    }