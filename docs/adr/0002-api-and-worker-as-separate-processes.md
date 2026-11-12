# The API and the background worker are separate processes

The FastAPI app and the background worker share code and models but run as separate processes (`uvicorn` and `python -m agrobot.worker`), rather than running background jobs inside the API process. This lets them scale and deploy independently, and keeps periodic work from competing with request handling. The cost is that the two processes can only coordinate through the database.
