FROM mirror.gcr.io/library/golang:1.24-alpine3.21 AS builder

ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z
ENV GOPROXY=https://proxy.golang.org|direct

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    apk add --no-cache git \
    && git clone --depth 1 --branch "${MINIO_RELEASE}" \
      https://github.com/minio/minio.git /src/minio \
    && cd /src/minio \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/minio .

FROM alpine:3.21.3

RUN apk add --no-cache ca-certificates curl

COPY --from=builder /out/minio /usr/local/bin/minio

RUN addgroup -S minio && adduser -S -G minio minio \
    && mkdir -p /data \
    && chown -R minio:minio /data

USER minio
VOLUME ["/data"]
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
