"""
End-to-end simulation of the pipeline's Gradle WAR build path.
Mimics exactly what _start_application does for a Gradle legacy app.
"""
import os, re, subprocess, shutil
from pathlib import Path

root = Path(r"C:\migrations\workspace_restores\015c410c-44bc-40b3-9dd6-dfa28f92cc55\scans-20260608-111842-b38f8495")
proxy_host = "internet.ford.com"
proxy_port = "83"

print("=" * 70)
print("  PIPELINE SIMULATION: Gradle WAR Build")
print("=" * 70)

# ── Step 1: JFrog credentials ──
art_user = art_password = None
settings_xml = Path.home() / ".m2" / "settings.xml"
if settings_xml.exists():
    sx = settings_xml.read_text(errors="replace")
    mu = re.search(r'<username>([^<]+)</username>', sx)
    mp = re.search(r'<password>([^<]+)</password>', sx)
    if mu and mp:
        art_user = mu.group(1).strip()
        art_password = mp.group(1).strip()
if art_user:
    print(f"[OK]  JFrog credentials: user={art_user}")
else:
    print("[WARN] No JFrog credentials found")

# ── Step 2: Create init.gradle (no BOM) ──
init_gradle = root / "init.gradle"
init_content = "allprojects {\n    buildscript {\n        repositories {\n            mavenCentral()\n            gradlePluginPortal()\n        }\n    }\n    repositories {\n        mavenCentral()\n    }\n}\n"
init_gradle.write_bytes(init_content.encode("utf-8"))
print(f"[OK]  Created init.gradle (no BOM, {len(init_content)} bytes)")

# ── Step 3: gradle.properties proxy ──
gp = root / "gradle.properties"
gp_text = gp.read_text(errors="ignore") if gp.exists() else ""
if "systemProp.http.proxyHost" not in gp_text:
    with open(gp, "a") as f:
        f.write(f"\nsystemProp.http.proxyHost={proxy_host}\nsystemProp.http.proxyPort={proxy_port}\nsystemProp.https.proxyHost={proxy_host}\nsystemProp.https.proxyPort={proxy_port}\n")
    print("[OK]  Injected proxy into gradle.properties")

# ── Step 4: Patch wrapper URL ──
wp = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
wp_text = wp.read_text(errors="replace")
m_zip = re.search(r'(gradle-[\d.]+(?:-rc-?\d+)?-(bin|all)\.zip)', wp_text)
if m_zip:
    gradle_zip = m_zip.group(1)
    official = f"https\\://services.gradle.org/distributions/{gradle_zip}"
    wp_text = re.sub(r'distributionUrl\s*=\s*.*', f'distributionUrl={official}', wp_text)
    wp.write_text(wp_text)
    print(f"[OK]  Patched distributionUrl → services.gradle.org/{gradle_zip}")

# ── Step 5: JDK compat check ──
java_cmd = shutil.which("java.exe") or "java"
m_ver = re.search(r'gradle-([\d.]+)', wp_text)
gradle_major = int(m_ver.group(1).split(".")[0]) if m_ver else 0
jdk_major = 0
jver = subprocess.run([java_cmd, "-version"], capture_output=True, text=True, timeout=10)
jm = re.search(r'"(\d+)[\._]', jver.stderr + jver.stdout)
if jm:
    jdk_major = int(jm.group(1))
compat_max = {6: 15, 7: 19, 8: 21, 9: 24}
max_jdk = compat_max.get(gradle_major, 99)
print(f"[INFO] System JDK: {jdk_major}, Gradle: {gradle_major}, Max JDK for Gradle: {max_jdk}")

if jdk_major > max_jdk:
    cache = Path.home() / ".javaapex" / "jdk-cache" / "jdk11"
    found = None
    for jp in cache.rglob("java.exe"):
        if "bin" in str(jp):
            found = str(jp)
            break
    if found:
        java_cmd = found
        print(f"[OK]  Using cached JDK 11: {java_cmd}")
    else:
        print("[FAIL] No compatible JDK cached — would download here")

# ── Step 6: spring-core downgrade if using downloaded JDK ──
orig_java = shutil.which("java.exe") or "java"
if java_cmd != orig_java:
    bg_text = (root / "build.gradle").read_text(errors="replace")
    if re.search(r'spring-core:6\.\d+', bg_text):
        bg_text = re.sub(r'(spring-core:)6\.\d+\.\d+', r'\1 5.3.39', bg_text)
        (root / "build.gradle").write_text(bg_text)
        print("[OK]  Downgraded spring-core 6.x → 5.3.39")
    else:
        print("[OK]  spring-core is already 5.x — no downgrade needed")

# ── Step 7: jakarta.servlet fix ──
modules_need = []
for bg in root.rglob("build.gradle"):
    if ".gradle" in str(bg.parent):
        continue
    java_src = bg.parent / "src" / "main" / "java"
    if not java_src.exists():
        continue
    for jf in java_src.rglob("*.java"):
        try:
            if "import jakarta.servlet" in jf.read_text(errors="ignore")[:3000]:
                modules_need.append(bg.parent)
                break
        except:
            continue

for mod in modules_need:
    bgp = mod / "build.gradle"
    bt = bgp.read_text(errors="replace")
    if "jakarta.servlet:jakarta.servlet-api" in bt:
        continue
    bt = bt.replace("javax.servlet:javax.servlet-api", "jakarta.servlet:jakarta.servlet-api")
    bt = re.sub(r"jakarta\.servlet:jakarta\.servlet-api:([34])\.\d+\.\d+", "jakarta.servlet:jakarta.servlet-api:5.0.0", bt)
    if "jakarta.servlet:jakarta.servlet-api" not in bt:
        has_war = "apply plugin: 'war'" in bt
        cfg = "providedCompile" if has_war else "implementation"
        bt += f"\ndependencies {{ {cfg} 'jakarta.servlet:jakarta.servlet-api:5.0.0' }}\n"
    bgp.write_text(bt)
    print(f"[OK]  Added jakarta.servlet-api to {mod.name}")

if not modules_need:
    print("[OK]  No jakarta.servlet imports found — no fix needed")

# ── Step 8: Build ──
proxy_jvm = [
    f"-Dhttp.proxyHost={proxy_host}", f"-Dhttp.proxyPort={proxy_port}",
    f"-Dhttps.proxyHost={proxy_host}", f"-Dhttps.proxyPort={proxy_port}",
    "-Dhttp.nonProxyHosts=localhost|127.0.0.1",
]
wrapper_jar = str(root / "gradle" / "wrapper" / "gradle-wrapper.jar")
env = os.environ.copy()
env["HTTP_PROXY"] = f"http://{proxy_host}:{proxy_port}"
env["HTTPS_PROXY"] = f"http://{proxy_host}:{proxy_port}"
if art_user:
    env["ARTIFACTORY_USER"] = art_user
    env["ARTIFACTORY_PASSWORD"] = art_password

gradle_base = [java_cmd, *proxy_jvm, "-classpath", wrapper_jar, "org.gradle.wrapper.GradleWrapperMain", "--init-script", str(init_gradle)]

print("\n[BUILD] Compiling...")
r = subprocess.run(gradle_base + ["compileJava", "-x", "test"], cwd=str(root), capture_output=True, text=True, timeout=300, env=env)
if r.returncode == 0:
    print("[OK]  Compile succeeded")
else:
    output = (r.stdout + r.stderr)
    errors = [l for l in output.split("\n") if "error:" in l.lower()]
    print(f"[WARN] Compile failed ({len(errors)} errors) — will try WAR build anyway")
    for e in errors[:5]:
        print(f"       {e.strip()[:120]}")

print("\n[BUILD] Building WAR...")
r2 = subprocess.run(gradle_base + ["war", "-x", "test"], cwd=str(root), capture_output=True, text=True, timeout=300, env=env)
if r2.returncode == 0:
    print("[OK]  WAR build succeeded")
else:
    print(f"[WARN] WAR build exited {r2.returncode}")

# ── Step 9: Find WAR ──
war_file = None
for d in [root / "PinnacleToolsWAR", root]:
    for w in d.rglob("*.war"):
        ws = str(w).replace("\\", "/")
        if "/build/" in ws or "/libs/" in ws:
            war_file = w
            break
    if war_file:
        break
if not war_file:
    for w in root.rglob("*.war"):
        war_file = w
        break

print()
if war_file:
    size = war_file.stat().st_size
    print(f"[SUCCESS] WAR file found: {war_file}")
    print(f"          Size: {size:,} bytes ({size/1024/1024:.1f} MB)")
else:
    print("[FAIL] No WAR file found!")
    print("       Compile output tail:")
    for line in (r.stdout + r.stderr).split("\n")[-10:]:
        print(f"       {line}")

print("\n" + "=" * 70)
