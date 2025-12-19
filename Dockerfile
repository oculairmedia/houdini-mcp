FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies from pyproject.toml
COPY pyproject.toml README.md ./
COPY houdini_mcp/ ./houdini_mcp/
RUN pip install --no-cache-dir .

# Expose MCP server port
EXPOSE 3055

# Run the server
CMD ["python", "-m", "houdini_mcp"]
