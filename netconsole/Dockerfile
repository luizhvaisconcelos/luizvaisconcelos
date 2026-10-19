FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 NETCONSOLE_DATA=/data
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 nc && mkdir /data && chown nc /data
COPY app ./app
USER nc
VOLUME /data
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uvicorn", "--factory", "app.main:app_factory", "--host", "0.0.0.0", "--port", "8080"]
