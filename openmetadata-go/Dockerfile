FROM golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN GOTOOLCHAIN=local GOMAXPROCS=2 GOMEMLIMIT=384MiB go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=2 GOMEMLIMIT=384MiB go build -p=2 -trimpath -o /metadata-go ./cmd/metadata-go

FROM scratch
COPY --from=build /metadata-go /metadata-go
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
USER 65532:65532
EXPOSE 8585
ENTRYPOINT ["/metadata-go"]
