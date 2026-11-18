# Read-only Postgres MCP server (mcp_servers/postgres_mcp_server.py), streamable HTTP on port 8000 at /mcp.
# Build context is the project folder (see docker-compose.yml).
FROM python:3.12-slim
RUN pip install --no-cache-dir "mcp==1.30.0" "psycopg[binary]==3.3.9"
COPY mcp_servers/postgres_mcp_server.py /app/postgres_mcp_server.py
EXPOSE 8000
CMD ["python", "/app/postgres_mcp_server.py"]
