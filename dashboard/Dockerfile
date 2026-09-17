FROM python:3.12-slim
WORKDIR /app
# Same pandas/pyarrow as the API image so the parquet files read identically.
RUN pip install --no-cache-dir \
      pandas==3.0.5 pyarrow==25.0.1 numpy==2.5.2 streamlit
COPY analysis.py ./
COPY scripts/ ./scripts/
COPY dashboard/ ./dashboard/
RUN chmod +x /app/dashboard/entrypoint.sh
EXPOSE 3000
ENTRYPOINT ["/app/dashboard/entrypoint.sh"]
