FROM python:3.12-slim
WORKDIR /app
# Same pandas/pyarrow as the API image so the parquet files read identically.
RUN pip install --no-cache-dir \
      pandas==3.0.5 pyarrow==25.0.1 numpy==2.5.2 streamlit
COPY dashboard/ ./dashboard/
EXPOSE 3000
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=3000", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
