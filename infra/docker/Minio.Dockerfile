FROM golang:1.24.8-bookworm AS build
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
RUN mkdir /data

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build --chown=65532:65532 /out/minio /minio
COPY --from=build --chown=65532:65532 /data /data
USER 65532:65532
ENV HOME=/data
ENTRYPOINT ["/minio"]
