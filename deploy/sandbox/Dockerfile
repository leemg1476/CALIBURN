FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
COPY src/caliburn/sandbox/runner.py /opt/runner.py
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python", "-I", "-B", "/opt/runner.py"]
