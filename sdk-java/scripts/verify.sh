#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mvn "$@" -B clean install
version=$(mvn "$@" -q -Dstyle.color=never -DforceStdout help:evaluate -Dexpression=project.version)
# Maven's evaluated value is used by the isolated consumer, including after bumps.
printf '%s\n' "$version" | LC_ALL=C grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || exit 1
consumer_dir=$(mktemp -d "${TMPDIR:-/tmp}/kompressr-java-consumer.XXXXXX")
trap 'rm -rf "$consumer_dir"' EXIT HUP INT TERM
mkdir -p "$consumer_dir/src/main/java"
cp scripts/consumer/pom.xml "$consumer_dir/pom.xml"
cp scripts/consumer/InstalledConsumer.java "$consumer_dir/src/main/java/InstalledConsumer.java"
mvn "$@" -B -Dkompressr.version="$version" -f "$consumer_dir/pom.xml" package dependency:build-classpath -Dmdep.outputFile=classpath.txt
mkdir -p "$consumer_dir/examples"
javac --release 17 -cp "$(cat "$consumer_dir/classpath.txt")" -d "$consumer_dir/examples" examples/*.java
java -Xmx64m -cp "$consumer_dir/target/classes:$(cat "$consumer_dir/classpath.txt")" InstalledConsumer
