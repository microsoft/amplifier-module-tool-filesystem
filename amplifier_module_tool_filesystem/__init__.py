"""Filesystem Tools Module for Amplifier.

Provides read, write, and edit tools for filesystem operations.
"""

# Amplifier module metadata
__amplifier_module_type__ = "tool"

import logging
from typing import Any

from amplifier_core import ModuleCoordinator

from .edit import EditTool
from .read import ReadTool
from .write import WriteTool

__all__ = ["ReadTool", "WriteTool", "EditTool", "mount"]

logger = logging.getLogger(__name__)


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None) -> None:
    """Mount filesystem tools.

    Args:
        coordinator: Module coordinator for registering tools
        config: Module configuration

    Returns:
        None
    """
    config = config or {}

    # Get session.working_dir capability if not explicitly configured
    # This ensures relative paths are resolved against the session's working directory
    # rather than the server process's current working directory
    if "working_dir" not in config:
        working_dir = coordinator.get_capability("session.working_dir")
        if working_dir:
            config["working_dir"] = working_dir
            logger.debug(f"Using session.working_dir: {working_dir}")

    # Create tool instances
    tools = [
        ReadTool(config, coordinator),
        WriteTool(config, coordinator),
        EditTool(config, coordinator),
    ]

    # Register tools with coordinator
    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    logger.info(f"Mounted {len(tools)} filesystem tools")
