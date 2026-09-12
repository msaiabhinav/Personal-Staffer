"""Bounded subprocess adapter output. Invoked only with explicit jobspy enablement."""

import datetime
import json
import logging
import math
import sys


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    return value


def run(config):
    import contextlib
    import io

    from jobspy import scrape_jobs

    errors = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errors.append({"logger": record.name, "code": "JOBSPY_REPORTED_ERROR"})

    handler = Capture()
    logging.getLogger().addHandler(handler)
    for name in list(logging.Logger.manager.loggerDict):
        if "jobspy" in name.lower():
            logging.getLogger(name).addHandler(handler)
    try:
        # Third-party prints cannot corrupt the machine-readable contract or leak raw source data.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            frame = scrape_jobs(**config)
        return {"rows": clean(frame.to_dict(orient="records")), "errors": errors}
    except Exception:  # noqa: BLE001 - Third-party scraper errors cross only the explicit typed error boundary.
        return {"rows": [], "errors": [{"code": "JOBSPY_EXCEPTION"}]}
    finally:
        logging.getLogger().removeHandler(handler)


if __name__ == "__main__":
    # Server baseline is Linux; bound third-party output and CPU within its child process.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (55, 60))
    except ImportError:
        pass
    print(json.dumps(run(json.loads(sys.stdin.read())), default=str, allow_nan=False))
