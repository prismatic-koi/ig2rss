# Agent Guidelines for ig2rss

## Workflow
- **ALWAYS run tests before committing**: Run tests with the proper environment setup to ensure all tests pass before making any commits. The Docker build includes a test stage that will fail if tests don't pass.

## Commands

**Important**: All commands must be run with the virtual environment activated and PYTHONPATH set:
```bash
source .venv/bin/activate
export PYTHONPATH=/home/ben/code/ig2rss
```

Or use the one-liner format:
```bash
cd /home/ben/code/ig2rss && source .venv/bin/activate && PYTHONPATH=/home/ben/code/ig2rss <command>
```

### Testing
- **Test all**: `PYTHONPATH=/home/ben/code/ig2rss pytest tests/ -v --cov=src --cov-report=term-missing`
- **Test single module**: `PYTHONPATH=/home/ben/code/ig2rss pytest tests/test_<module>.py -v`
- **Test single test**: `PYTHONPATH=/home/ben/code/ig2rss pytest tests/test_<module>.py::<TestClass>::<test_name> -v`
- **Quick syntax check**: `python3 -m py_compile src/<file>.py`

### Code Quality
- **Lint**: `flake8 src/ tests/`
- **Format**: `black src/ tests/`
- **Type check**: `mypy src/ --ignore-missing-imports`

### Running the App
- **Run locally**: `./test-local.sh` (interactive script for Docker/direct Python)
- **Run app**: `PYTHONPATH=/home/ben/code/ig2rss python -m src.main` (requires .env file with credentials)

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
