"""Kaggle phase handoff; the competition gateway owns all scored output."""

from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


GATEWAY_GAMES_URL = "http://gateway:8001/api/games"


def run_checked(*args, **kwargs):
    try:
        return subprocess.run(*args, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print("Child process failed:", type(error).__name__)
        for label in ("stdout", "stderr"):
            value = getattr(error, label, None)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if value:
                print(label + " (last 16384 characters):\n" + value[-16384:])
        print("No operation is retried. A gateway scorecard may already be closed.")
        raise


def run_postclose_diagnostic(report, *args, **kwargs):
    if report.get("status") != "protocol_completed" or report.get("scorecard_cleanup", {}).get("status") != "closed":
        raise RuntimeError("local diagnostics require a completed protocol and confirmed scorecard closure")
    completed = run_checked(*args, check=False, **kwargs)
    diagnostic = {
        "status": "passed" if completed.returncode == 0 else "diagnostic_failed",
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "")[-16384:],
        "stderr": (completed.stderr or "")[-16384:],
    }
    if completed.returncode:
        print("Post-closure local diagnostic failed; gateway protocol already completed.")
        print(diagnostic)
    return diagnostic


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, stream, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code, "gateway redirect refused", headers, stream)


def wait_for_gateway(rerun, *, opener=None, clock=time.monotonic, sleep=time.sleep, timeout=600):
    if not rerun:
        return
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    deadline = clock() + timeout
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("competition gateway did not become ready")
        try:
            with opener.open(GATEWAY_GAMES_URL, timeout=min(10, remaining)) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("competition gateway did not become ready")
        sleep(min(5, remaining))


def write_commit_placeholder(rerun, output="/kaggle/working/submission.parquet", *, dataframe_factory=None):
    if rerun:
        return None
    if dataframe_factory is None:
        import pandas

        dataframe_factory = pandas.DataFrame
    output = Path(output)
    if not output.parent.is_dir():
        raise RuntimeError("Kaggle working directory is required for commit output")
    if output.exists():
        raise FileExistsError("refusing to overwrite an existing submission artifact")
    # Kaggle selects this file for Phase B; it contains no measured result.
    frame = dataframe_factory(
        [["1_0", "1", True, 0.0]],
        columns=["row_id", "game_id", "end_of_game", "score"],
    )
    frame.to_parquet(output, index=False)
    return output
