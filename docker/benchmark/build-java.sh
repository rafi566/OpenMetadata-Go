#!/usr/bin/env bash
set -euo pipefail

if [[ "$(git -c safe.directory="$PWD" rev-parse HEAD)" != "$BASELINE_SOURCE_SHA" ]]; then
  echo "Refusing a Java baseline from a different source revision" >&2
  exit 1
fi
if [[ -n "$(git -c safe.directory="$PWD" status --porcelain --untracked-files=all)" ]]; then
  echo "Refusing a Java baseline with modified or untracked source" >&2
  exit 1
fi
mvn -s /benchmark/maven-settings.xml -Dmaven.repo.local=/maven-cache \
  -B -ntp -pl openmetadata-service -am install -Dmaven.test.skip=true
mvn -s /benchmark/maven-settings.xml -Dmaven.repo.local=/maven-cache \
  -B -ntp -pl openmetadata-service dependency:copy-dependencies \
  -DincludeScope=runtime -DoutputDirectory=/source/target/benchmark-libs
# Jetty needs the provided Servlet API ahead of Felix's bundled older API.
mvn -s /benchmark/maven-settings.xml -Dmaven.repo.local=/maven-cache \
  -B -ntp -pl openmetadata-service dependency:copy-dependencies \
  -DincludeScope=compile -DincludeArtifactIds=jakarta.servlet-api \
  -DoutputDirectory=/source/target/benchmark-provided
mkdir -p /source/logs
printf '%s\n' "$BASELINE_SOURCE_SHA" > /source/target/benchmark-source-sha.txt
