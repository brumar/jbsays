#!/bin/sh
set -e

# Default arguments and port
MCP_ARGS=""
# Use MCP_PORT from environment or default to 8931
INTERNAL_PORT=${MCP_PORT:-8931}

# Add --headless if HEADLESS environment variable is true
if [ "$HEADLESS" = "true" ]; then
  MCP_ARGS="$MCP_ARGS --headless"
fi

# Add --port if MCP_PORT is set (for SSE connection)
# This allows SSE connection even when HEADLESS=true
if [ -n "$MCP_PORT" ]; then
  MCP_ARGS="$MCP_ARGS --port $INTERNAL_PORT"
fi

# Add other options if needed (e.g., --vision)
# if [ "$VISION_MODE" = "true" ]; then
#   MCP_ARGS="$MCP_ARGS --vision"
# fi

echo "Starting @playwright/mcp with args: $MCP_ARGS $@"
echo "Internal MCP port (if using SSE): $INTERNAL_PORT"

# Execute @playwright/mcp using npx, passing arguments ($@)
exec npx @playwright/mcp@0.0.7 $MCP_ARGS "$@"
