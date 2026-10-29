from __future__ import annotations

__version__ = "0.2.0"

# Kept separate from config so packaging metadata, the API, export manifests and
# the Docker build arg can all read one source of truth.
PIPELINE_VERSION = "0.2.0"
EXPORT_FORMAT = "persona-package+agentskills"