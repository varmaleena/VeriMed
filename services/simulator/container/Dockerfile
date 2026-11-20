# Build from the repository root; copy only the explicitly listed runtime inputs.
FROM eclipse-temurin:21-jre-alpine@sha256:ac05c3c42b7c2f1a52c9bd52f01041fa1958231b15ebeae7420429cbc5baf474 AS java
FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
RUN apk upgrade --no-cache && apk add --no-cache libstdc++ zlib coreutils
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH="/opt/java/openjdk/bin:${PATH}" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app HOME=/work TMPDIR=/work \
    LANG=C.UTF-8 LC_ALL=C.UTF-8
COPY .build-synthea/requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r /opt/requirements.txt
COPY .build-synthea/synthea.jar /opt/synthea.jar
RUN echo 'ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1  /opt/synthea.jar' | sha256sum -c - \
    && mkdir /work && chown 10001:10001 /work
COPY services/simulator/simulator /app/simulator
USER 10001:10001
VOLUME ["/work"]
WORKDIR /work
# Hard wall-clock limit also bounds upload retries; logs contain fixed error codes only.
ENTRYPOINT ["timeout", "--signal=TERM", "--kill-after=20s", "35m", "python", "-m", "simulator.hosted_synthea"]
