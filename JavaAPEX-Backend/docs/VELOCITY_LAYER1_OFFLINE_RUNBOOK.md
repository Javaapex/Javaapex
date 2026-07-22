# Velocity Layer 1 — Offline / Blocked-Mirror Runbook

This box's `mvn test` for the generated Velocity Layer 1 project failed with:

```
Could not transfer artifact org.apache.velocity:velocity-engine-core:pom:2.3
from/to central (https://repo.maven.apache.org/maven2): No such host is known
```

That is **degradation reason 2.2** (Maven Central unreachable / blocked mirror).
The local repository (`%USERPROFILE%\.m2\repository`) only contained
`*.pom.lastUpdated` failure markers — i.e. the cache was **not warmed**.

There are two supported ways forward.

## Option A — Route through the internal Ford Nexus/Artifactory mirror

1. Copy `docs/ford-nexus-settings.xml` to `%USERPROFILE%\.m2\settings.xml`.
2. Replace the placeholder URL `https://REPLACE-ME.nexus.internal.ford.com/...`
   with your team's real internal mirror URL.
3. Re-run:
   ```powershell
   mvn -B "-Dvelocity.template.dir=templates" test
   ```

## Option B — Warm `~/.m2` on a connected machine, then copy it over

On a machine that CAN reach Maven Central (or the mirror), run
`dependency:go-offline` against the generated project so every jar/pom/plugin
is downloaded into the local repo:

```powershell
# 1) On the connected machine, in the generated velocity/ project:
mvn -B dependency:go-offline
mvn -B "-Dvelocity.template.dir=templates" test   # optional: prove it compiles

# 2) Copy the warmed repository to the locked-down box.
#    Only these coordinates are needed for Layer 1:
#      org/apache/velocity/velocity-engine-core/2.3
#      org/jsoup/jsoup/1.17.2
#      org/junit/jupiter/**            (5.10.2 + transitive)
#      org/apache/maven/plugins/maven-surefire-plugin/3.2.5
#      org/apache/maven/plugins/maven-compiler-plugin/3.13.0
#    Easiest: zip the whole ~/.m2/repository and unzip on the target box.
Compress-Archive -Path "$env:USERPROFILE\.m2\repository\*" -DestinationPath m2-warm.zip
```

```powershell
# 3) On the locked-down box:
Expand-Archive -Path m2-warm.zip -DestinationPath "$env:USERPROFILE\.m2\repository" -Force
# Remove any stale failure markers so Maven stops trying central:
Get-ChildItem "$env:USERPROFILE\.m2\repository" -Recurse -Filter *.lastUpdated | Remove-Item -Force
# Then build fully offline:
mvn -o -B "-Dvelocity.template.dir=templates" test
```

> Tip: `*.lastUpdated` markers make Maven believe a download was already tried
> and failed. Deleting them is required after warming the cache out-of-band.
