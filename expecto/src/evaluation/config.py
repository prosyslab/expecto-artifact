import contextvars
import datetime
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, get_type_hints

from pydantic import BaseModel, Field

# ContextVar for sample_id (Kept outside of Config as it's a runtime variable)
sample_id_var = contextvars.ContextVar("sample_id", default="N/A")

project_root = Path(__file__).parent.parent.parent


class Config(BaseModel):
    """
    Configuration for the evaluation module.

    This class manages configuration values from multiple sources in order of precedence:
    1. Configuration files (lowest priority)
    2. Environment variables (prefixed with EXPECTO_)
    3. Explicitly provided values (highest priority)

    Example usage:
        # Get the global config instance
        from evaluation.config import config

        # Access a config value
        max_sandboxes = config.MAX_SANDBOXES

        # Load config from a custom file
        custom_config = Config(CONFIG_FILE='/path/to/custom/config.json')

        # Update a config value
        config.DEFAULT_EXECUTION_TIMEOUT = 60

        # Save current config to a file
        config.save_to_file('/path/to/save/config.json')
    """

    # Resources configuration
    MAX_SANDBOXES: int = Field(
        32, description="Max concurrent sandboxes"
    )
    MAX_SUBPROCESS_CONCURRENT: int = Field(
        64, description="Max concurrent subprocesses"
    )
    MAX_CONSUMER_PROCESSES: int = Field(
        64,
        description=(
            "Upper bound for worker processes; effective count is also limited by available CPUs and sample count"
        ),
    )
    DEFAULT_EXECUTION_TIMEOUT: int = Field(
        30, description="Default timeout for code execution in seconds"
    )
    PYTHON_EXECUTABLE: str = Field(
        "python3", description="Python command used inside the sandbox"
    )

    # Paths configuration
    PROJECT_ROOT: str = Field(os.getcwd(), description="Project root directory")
    SANDBOXES_PARENT_DIR: Optional[str] = Field(
        None, description="Base directory for creating temporary sandboxes"
    )

    # Logging configuration
    LOG_LEVEL: str = Field(
        "INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    LOG_FORMAT: str = Field(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        description="Log message format",
    )
    LOG_DATE_FORMAT: str = Field("%Y-%m-%d %H:%M:%S", description="Log date format")
    LOG_FILE_DIR: str = Field("logs", description="Directory for log files")
    LOG_FILE_MAX_SIZE_MB: int = Field(
        10, description="Maximum size of log file in MB before rotation"
    )
    LOG_FILE_BACKUP_COUNT: int = Field(
        20, description="Number of backup log files to keep"
    )

    # Config file location (defaults to config.json in project root)
    CONFIG_FILE: Optional[str] = Field(
        None, description="Path to configuration file (JSON or YAML)"
    )

    def __init__(self, **data):
        # Determine config file path
        config_file = data.get("CONFIG_FILE")
        if config_file is None:
            config_file = os.environ.get("EXPECTO_CONFIG_FILE")
        if config_file is None:
            # Default to config.json in project root
            config_file = os.path.join(os.getcwd(), "config.json")

        # Load config in order of precedence:
        # 1. File-based config (lowest priority)
        config_data = {}
        if os.path.exists(config_file):
            config_data = self._load_from_file(config_file)

        # 2. Environment variables (overrides file-based config)
        env_data = self._load_from_env()
        config_data.update(env_data)

        # 3. Explicit kwargs (highest priority)
        config_data.update(data)

        # Store CONFIG_FILE value for reference
        config_data["CONFIG_FILE"] = config_file

        super().__init__(**config_data)

        # Set derived path values if not explicitly provided
        if self.SANDBOXES_PARENT_DIR is None:
            self.SANDBOXES_PARENT_DIR = os.path.join(
                self.PROJECT_ROOT, ".llm_sandboxes"
            )

        # Setup logging
        self._setup_logging()

    def _load_from_env(self) -> Dict[str, Any]:
        """
        Load configuration values from environment variables.
        Environment variables should be prefixed with 'EXPECTO_'
        (e.g., EXPECTO_MAX_SANDBOXES).
        """
        result = {}
        type_hints = get_type_hints(self.__class__)

        for field_name in self.__dict__:
            env_name = f"EXPECTO_{field_name}"
            env_value = os.environ.get(env_name)
            if env_value is not None:
                # Get the expected type for this field
                field_type = type_hints.get(field_name)

                # Convert the env value to the appropriate type
                if field_type is int:
                    result[field_name] = int(env_value)
                elif field_type is bool:
                    result[field_name] = env_value.lower() in ("true", "1", "yes")
                else:
                    result[field_name] = env_value
        return result

    def _load_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Load configuration from a file (JSON or YAML).

        Args:
            file_path: Path to the configuration file

        Returns:
            Dictionary containing the configuration values
        """
        try:
            if file_path.endswith(".json"):
                with open(file_path, "r") as f:
                    return json.load(f)
            elif file_path.endswith((".yaml", ".yml")):
                try:
                    import yaml

                    with open(file_path, "r") as f:
                        return yaml.safe_load(f)
                except ImportError:
                    print(
                        "Warning: YAML file specified but PyYAML not installed. "
                        "Skipping file-based configuration."
                    )
            else:
                print(f"Warning: Unsupported config file format: {file_path}")
        except Exception as e:
            print(f"Error loading config file {file_path}: {str(e)}")
        return {}

    def _setup_logging(self, path=None):
        """Setup logging to write to file instead of console"""
        # Create logs directory if it doesn't exist
        if path is None:
            log_dir = os.path.join(self.PROJECT_ROOT, self.LOG_FILE_DIR)
        else:
            log_dir = path
        os.makedirs(log_dir, exist_ok=True)

        # Generate log filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"evaluation_{timestamp}.log")

        # Set up rotating file handler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.LOG_FILE_MAX_SIZE_MB * 1024 * 1024,
            backupCount=self.LOG_FILE_BACKUP_COUNT,
        )
        file_handler.setLevel(getattr(logging, self.LOG_LEVEL))
        file_handler.setFormatter(
            logging.Formatter(
                fmt=self.LOG_FORMAT,
                datefmt=self.LOG_DATE_FORMAT,
            )
        )

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.LOG_LEVEL))

        # Remove all existing handlers to ensure we don't output to console
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Add file handler
        root_logger.addHandler(file_handler)

    def save_to_file(self, file_path: Optional[str] = None) -> bool:
        """
        Save the current configuration to a file.

        Args:
            file_path: Path to save to (defaults to self.CONFIG_FILE)

        Returns:
            True if successful, False otherwise
        """
        if file_path is None:
            file_path = self.CONFIG_FILE

        if file_path is None:
            return False

        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

            if file_path.endswith(".json"):
                with open(file_path, "w") as f:
                    json.dump(self.model_dump(), f, indent=2)
                return True
            elif file_path.endswith((".yaml", ".yml")):
                try:
                    import yaml

                    with open(file_path, "w") as f:
                        yaml.dump(self.model_dump(), f)
                    return True
                except ImportError:
                    print("Warning: PyYAML not installed. Cannot save to YAML format.")
            else:
                print(f"Warning: Unsupported config file format: {file_path}")
        except Exception as e:
            print(f"Error saving config to {file_path}: {str(e)}")
        return False

    def as_dict(self) -> Dict[str, Any]:
        """Return the configuration as a dictionary"""
        return self.model_dump()

    def __str__(self) -> str:
        """Return a string representation of the configuration"""
        return "\n".join(f"{k}={v}" for k, v in self.model_dump().items())


# Create a global config instance
config = Config()
