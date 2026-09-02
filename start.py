"""One-click ShipMate launcher — FastAPI server + browser."""

import threading
import time

import uvicorn

from runner import open_browser


def main() -> None:
    def _open_browser() -> None:
        time.sleep(1.5)
        open_browser("http://127.0.0.1:5000")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("server:app", host="127.0.0.1", port=5000, reload=False)


if __name__ == "__main__":
    main()
