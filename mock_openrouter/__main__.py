"""Run the mock OpenRouter over HTTP: `python -m mock_openrouter`."""
import uvicorn

from mock_openrouter.app import MockSettings, build_app


def main() -> None:
    settings = MockSettings()
    uvicorn.run(build_app(settings), host="0.0.0.0", port=settings.PORT)


if __name__ == "__main__":
    main()
