FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY houdini_mcp/ ./houdini_mcp/

# Expose MCP server port
EXPOSE 3055

# Run the server
CMD ["python", "-m", "houdini_mcp.server"]
