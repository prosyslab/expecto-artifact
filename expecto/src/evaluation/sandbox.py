import asyncio
import logging
import os
import shutil
import signal
import sys
import tempfile
import uuid
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.evaluation.config import config, sample_id_var
from src.evaluation.models import ExecutionResult

# Global semaphore - will be initialized in main.py
sandbox_semaphore: Optional[asyncio.Semaphore] = asyncio.Semaphore(12)
subprocess_semaphore: Optional[asyncio.Semaphore] = asyncio.Semaphore(12)


def init_sandbox_semaphore(max_sandboxes: int) -> None:
    """Initialize the sandbox semaphore. Should be called from main.py"""
    global sandbox_semaphore
    sandbox_semaphore = asyncio.Semaphore(max_sandboxes)


def init_subprocess_semaphore() -> None:
    """Initialize the subprocess semaphore. Should be called from main.py"""
    global subprocess_semaphore
    subprocess_semaphore = asyncio.Semaphore(config.MAX_SUBPROCESS_CONCURRENT)


def initialize():
    init_sandbox_semaphore(config.MAX_SANDBOXES)
    init_subprocess_semaphore()
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(event)))


logger = logging.getLogger(__name__)

# Registry to keep track of active sandboxes
_active_sandboxes: weakref.WeakSet["Sandbox"] = weakref.WeakSet()
cleanup_lock: Optional[asyncio.Lock] = asyncio.Lock()
_cleanup_in_progress = False


class Sandbox:
    """
    An abstract sandbox environment that provides a safe execution environment.

    This class provides two main functionalities:
    1. File writing within the sandbox
    2. Command execution with timeout
    """

    def __init__(self, sandbox_id: Optional[str] = None, no_cleanup: bool = False):
        """
        Initialize a new sandbox environment.

        Args:
            sandbox_id: Optional unique identifier for the sandbox
            no_cleanup: If True, the sandbox will not be cleaned up automatically
        """
        self.sandbox_id = sandbox_id or str(uuid.uuid4())
        # Register this sandbox in the global registry
        _active_sandboxes.add(self)
        self.no_cleanup = no_cleanup

    def _ensure_sandbox_dir(self) -> None:
        """Create or re-create the sandbox directory and set proper permissions.

        - If `self.sandbox_dir` is missing, create a new temporary directory under the
          configured parent and record its path.
        - If `self.sandbox_dir` exists but was deleted, recreate it.
        - Always ensure permissions allow container/user access.
        """
        try:
            # Determine parent directory for sandboxes
            sandboxes_dir = config.SANDBOXES_PARENT_DIR or os.path.join(
                os.getcwd(), ".sandboxes"
            )
            os.makedirs(sandboxes_dir, exist_ok=True)

            # Create the sandbox directory if not set yet
            if not hasattr(self, "sandbox_dir"):
                self.sandbox_dir = tempfile.mkdtemp(
                    prefix=f"sandbox_{self.sandbox_id}_", dir=sandboxes_dir
                )

            # If path missing, recreate it (keeps same path for existing sandboxes)
            if not os.path.exists(self.sandbox_dir):
                os.makedirs(self.sandbox_dir, exist_ok=True)

            # Ensure broad permissions for bind mounts / container users
            os.chmod(self.sandbox_dir, 0o777)
        except Exception as e:
            logger.error(
                f"Failed to ensure sandbox directory for sandbox {self.sandbox_id}: {e}"
            )
            raise

    async def write_file(self, filename: str, content: str) -> str:
        """
        Write content to a file inside the sandbox.

        Args:
            filename: Name of the file to write
            content: Content to write to the file

        Returns:
            Full path to the written file
        """
        # Ensure sandbox directory exists
        try:
            self._ensure_sandbox_dir()
        except Exception as e:
            raise RuntimeError(
                f"Failed to ensure sandbox directory for sandbox {self.sandbox_id}: {str(e)}"
            )

        file_path = os.path.join(self.sandbox_dir, filename)

        # Create directories if needed
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        with open(file_path, "w") as f:
            f.write(content)
            f.flush()

        # Ensure the container user can read the file through the bind mount
        try:
            os.chmod(file_path, 0o666)
        except Exception as e:
            logger.warning(f"Failed to chmod sandbox file {file_path} to 0666: {e}")

        logger.debug(f"Wrote file {filename} in sandbox {self.sandbox_id}")
        return file_path

    async def exec(
        self,
        args: List[str],
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        Execute a command in the sandbox with a timeout.

        Args:
            args: Command and arguments to execute
            timeout: Timeout in seconds for the command execution
            env: Optional environment variables to set for the command

        Returns:
            ExecutionResult containing the execution status and outputs
        """
        start_time = asyncio.get_event_loop().time()
        timeout = timeout or config.DEFAULT_EXECUTION_TIMEOUT

        logger.debug(
            f"Executing command in sandbox {self.sandbox_id}: {' '.join(args)}"
        )

        # Ensure sandbox directory exists before executing command
        try:
            self._ensure_sandbox_dir()
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            return ExecutionResult(
                sample_id=sample_id_var.get(),
                status="error",
                stderr=f"Failed to ensure sandbox directory for sandbox {self.sandbox_id}: {str(e)}",
                duration=duration,
            )

        try:
            # Note: run_subprocess doesn't support env parameter, so it's ignored
            exit_code, stdout, stderr = await run_subprocess(
                args, timeout=timeout, cwd=self.sandbox_dir, stdin=stdin
            )

            duration = asyncio.get_event_loop().time() - start_time

            logger.debug(
                f"Execution finished in sandbox {self.sandbox_id}. "
                f"Exit: {exit_code}, Duration: {duration:.2f}s"
            )

            if exit_code == 137:  # OOM case
                stderr = "Out of memory"

            return ExecutionResult(
                sample_id=sample_id_var.get(),
                status="success" if exit_code == 0 else "failure",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration=duration,
            )

        except asyncio.TimeoutError:
            duration = asyncio.get_event_loop().time() - start_time
            logger.warning(
                f"Command execution timed out in sandbox {self.sandbox_id} after {timeout}s"
            )
            return ExecutionResult(
                sample_id=sample_id_var.get(),
                status="timeout",
                stderr="timeout",
                duration=duration,
            )

        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(
                f"Error during command execution in sandbox {self.sandbox_id}: {e}",
                exc_info=True,
            )
            return ExecutionResult(
                sample_id=sample_id_var.get(),
                status="error",
                stderr=f"{e.__class__.__name__} during command execution in sandbox {self.sandbox_id}: {str(e)}",
                duration=duration,
            )

    async def run_test(self, code: str, timeout: float = 30.0) -> ExecutionResult:
        test_file_name = f"{uuid.uuid4()}.py"
        await self.write_file(test_file_name, code)
        return await self.exec(
            [config.PYTHON_EXECUTABLE, test_file_name], timeout=timeout
        )

    async def run_test_with_io(
        self, code: str, test_list: list[tuple[str, str]], timeout: float = 30.0
    ) -> ExecutionResult:
        test_file_name = f"{uuid.uuid4()}.py"
        await self.write_file(test_file_name, code)
        duration = 0.0
        for stdin, stdout in test_list:
            result = await self.exec(
                [config.PYTHON_EXECUTABLE, test_file_name], timeout=timeout, stdin=stdin
            )
            duration += result.duration
            if result.stdout is None or result.stdout.strip() != stdout.strip():
                return ExecutionResult(
                    sample_id=sample_id_var.get(),
                    status="failure",
                    stderr=f"Test case failed: {stdin} -> {stdout}\n\n{result.stderr}",
                    duration=duration,
                )
        return ExecutionResult(
            sample_id=sample_id_var.get(),
            status="success",
            stdout=stdout,
            stderr="",
            duration=duration,
        )

    async def cleanup(self) -> None:
        """Clean up the sandbox by removing its directory"""
        if self.no_cleanup:
            return

        if os.path.exists(self.sandbox_dir):
            try:
                shutil.rmtree(self.sandbox_dir)
                logger.debug(f"Removed sandbox directory {self.sandbox_dir}")
            except Exception as e:
                logger.error(
                    f"Failed to remove sandbox directory {self.sandbox_dir}: {e}"
                )

        # Remove from active sandboxes registry
        if self in _active_sandboxes:
            _active_sandboxes.discard(self)

    async def __aenter__(self) -> "Sandbox":
        if sandbox_semaphore is None:
            raise RuntimeError(
                "Sandbox semaphore not initialized. Call init_sandbox_semaphore() first."
            )
        await sandbox_semaphore.acquire()
        logger.debug(f"Get semaphore for sandbox {self.sandbox_id}")

        try:
            # Create sandbox directory
            self._ensure_sandbox_dir()
            logger.debug(f"Created/ensured sandbox at {self.sandbox_dir}")
            return self
        except Exception as e:
            logger.error(f"Failed to create sandbox {self.sandbox_id}: {e}")
            # Release semaphore if we acquired it but failed to create sandbox
            if sandbox_semaphore is not None:
                sandbox_semaphore.release()
            raise

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.cleanup()
        if sandbox_semaphore is not None:
            sandbox_semaphore.release()


# Signal handlers and cleanup functions


async def _cleanup_all_sandboxes() -> None:
    """Clean up all active sandboxes"""
    global _cleanup_in_progress

    if _cleanup_in_progress:
        return

    if cleanup_lock is None:
        # If cleanup_lock is not initialized, just do cleanup without lock
        _cleanup_in_progress = True
        logger.warning(
            f"Emergency cleanup of {len(_active_sandboxes)} sandbox(es) (no lock)"
        )

        cleanup_tasks = []
        for sandbox in list(_active_sandboxes):
            try:
                cleanup_tasks.append(
                    asyncio.create_task(sandbox.__aexit__(None, None, None))
                )
            except Exception as e:
                logger.error(
                    f"Error creating cleanup task for sandbox {sandbox.sandbox_id}: {e}"
                )

        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        _cleanup_in_progress = False
        logger.debug("Emergency sandbox cleanup completed")
        return

    async with cleanup_lock:
        _cleanup_in_progress = True
        logger.warning(f"Emergency cleanup of {len(_active_sandboxes)} sandbox(es)")

        cleanup_tasks = []
        for sandbox in list(_active_sandboxes):
            try:
                cleanup_tasks.append(
                    asyncio.create_task(sandbox.__aexit__(None, None, None))
                )
            except Exception as e:
                logger.error(
                    f"Error creating cleanup task for sandbox {sandbox.sandbox_id}: {e}"
                )

        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        _cleanup_in_progress = False
        logger.debug("Emergency sandbox cleanup completed")


async def shutdown(e: asyncio.Event):
    this = asyncio.current_task()
    to_cancel = {t for t in asyncio.all_tasks() if t is not this and not t.done()}

    for t in to_cancel:
        t.cancel()

    await asyncio.gather(*to_cancel, return_exceptions=True)
    await asyncio.sleep(0)
    await asyncio.shield(_cleanup_all_sandboxes())
    e.set()


async def run_subprocess(
    cmd_args: List[str],
    *,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    stdin: Optional[str] = None,
) -> Tuple[int, str, str]:
    """
    Runs a subprocess asynchronously.

    Args:
        cmd_args: The command arguments to run
        timeout: Optional timeout in seconds
        cwd: Optional working directory

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if subprocess_semaphore is None:
        raise RuntimeError(
            "Subprocess semaphore not initialized. Call init_subprocess_semaphore() first."
        )

    async with subprocess_semaphore:
        logger.debug(f"Running command: {' '.join(cmd_args)} in cwd: {cwd}")
        stdin_pipe = asyncio.subprocess.PIPE if stdin is not None else None
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=stdin_pipe,
            cwd=cwd,
            close_fds=True,
        )
        try:
            input_bytes = stdin.encode() if stdin is not None else None
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Process {' '.join(cmd_args)} timed out. Terminating...")
            try:
                process.terminate()
                await asyncio.wait_for(
                    process.wait(), timeout=30.0
                )  # Give 5s to terminate
                logger.warning(f"Process {' '.join(cmd_args)} terminated gracefully")
            except asyncio.TimeoutError:
                logger.warning(
                    f"Process {' '.join(cmd_args)} did not terminate gracefully. Killing..."
                )
                process.kill()
                logger.error(f"Process {' '.join(cmd_args)} killed")
            except ProcessLookupError:
                logger.warning(
                    f"Process {' '.join(cmd_args)} not found. Terminating..."
                )
            finally:
                if process.stdin is not None:
                    process.stdin.close()
            raise  # Re-raise the TimeoutError to be handled by the caller

        return (
            process.returncode if process.returncode is not None else -1,
            stdout_bytes.decode(errors="replace").strip(),
            stderr_bytes.decode(errors="replace").strip(),
        )


