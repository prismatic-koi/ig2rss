# Agent Guidelines for ig2rss

## Commands
- **Test all**: `pytest tests/ -v --cov=src --cov-report=term-missing`
- **Test single**: `pytest tests/test_<module>.py::<TestClass>::<test_name> -v`
- **Lint**: `flake8 src/ tests/`
- **Format**: `black src/ tests/`
- **Type check**: `mypy src/`
- **Run locally**: `./test-local.sh` (interactive script for Docker/direct Python)
- **Run app**: `python -m src.main` (requires .env file with credentials)

## Code Style
- **Formatting**: Use Black (line length 88). Run before committing.
- **Imports**: Standard lib → third-party → local. Use absolute imports (`from src.module import ...`).
- **Types**: Always use type hints on function signatures. Use `Optional[T]` for nullable values.
- **Docstrings**: Google style for all public functions/classes. Include Args, Returns, Raises sections.
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants.
- **Error handling**: Use specific exceptions. Log errors with context (`logger.error(f"msg: {e}", exc_info=True)`).
- **Logging**: Use module-level logger: `logger = logging.getLogger(__name__)`. Info for key events, debug for details.
- **Dataclasses**: Use `@dataclass` for data structures (see `InstagramPost`).

## Architecture
- Flask API serves RSS feeds and media files (`src/api.py`)
- Background scheduler polls Instagram timeline every N seconds (APScheduler)
- SQLite for post metadata, filesystem for media cache (`/data/`)
- Instagram client uses session persistence to avoid repeated logins
