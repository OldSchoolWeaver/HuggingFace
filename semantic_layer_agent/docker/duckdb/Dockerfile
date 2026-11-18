# DuckDB "query & compute" service: an in-memory DuckDB that attaches the Postgres fleet database
# (read-only) and the files in /data, served to the agent over MCP (streamable HTTP on port 8000).
FROM python:3.12-slim
RUN pip install --no-cache-dir "mcp-server-motherduck==1.1.1"
# Download the Postgres extension at build time, so the container needs no internet at runtime
RUN python -c "import duckdb; duckdb.connect().sql('INSTALL postgres')"
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 8000
CMD ["/start.sh"]
