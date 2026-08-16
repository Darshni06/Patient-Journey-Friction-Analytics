FROM python:3.11-slim

# Java is required for PySpark
RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The actual Hospital_log.xes is NOT baked into the image - mount it at
# runtime, e.g.:
#   docker run -v /path/to/Hospital_log.xes:/app/Hospital_log.xes ...

EXPOSE 8501

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0"]
