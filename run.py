"""Run the installed local application. See README.md for setup."""
import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Contour robotics research console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("mapper.app:app", host=args.host, port=args.port, reload=args.reload)
