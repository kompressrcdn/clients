#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mvn "$@" -B clean install
consumer_dir=$(mktemp -d "${TMPDIR:-/tmp}/kompressr-java-consumer.XXXXXX")
trap 'rm -rf "$consumer_dir"' EXIT HUP INT TERM
mkdir -p "$consumer_dir/src/main/java"
cp scripts/consumer/pom.xml "$consumer_dir/pom.xml"
cp scripts/consumer/InstalledConsumer.java "$consumer_dir/src/main/java/InstalledConsumer.java"
mvn "$@" -B -f "$consumer_dir/pom.xml" package dependency:build-classpath -Dmdep.outputFile=classpath.txt
mkdir -p "$consumer_dir/examples"
javac --release 17 -cp "$(cat "$consumer_dir/classpath.txt")" -d "$consumer_dir/examples" examples/*.java
java -Xmx64m -cp "$consumer_dir/target/classes:$(cat "$consumer_dir/classpath.txt")" InstalledConsumer
