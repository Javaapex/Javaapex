"""
End-to-end simulation v2: includes auto-fix for missing java.time imports.
Exactly mirrors what the pipeline does now.
"""
import os, re, subprocess, shutil
from pathlib import Path

root = Path(r"C:\migrations\workspace_restores\015c410c-44bc-40b3-9dd6-dfa28f92cc55\scans-20260608-111842-b38f8495")
proxy_host = "internet.ford.com"
proxy_port = "83"

print("=" * 70)
print("  PIPELINE SIMULATION v2: Full Gradle WAR Build")
print("=" * 70)

# Step 1: JFrog credentials
sx = (Path.home() / ".m2" / "settings.xml").read_text(errors="replace")
art_user = re.search(r'<username>([^<]+)</username>', sx).group(1).strip()
art_pass = re.search(r'<password>([^<]+)</password>', sx).group(1).strip()
print(f"[1/9] JFrog credentials: user={art_user}")

# Step 2: init.gradle
init_gradle = root / "init.gradle"
init_gradle.write_bytes(b"allprojects {\n    buildscript { repositories { mavenCentral(); gradlePluginPortal() } }\n    repositories { mavenCentral() }\n}\n")
print(f"[2/9] init.gradle created (no BOM)")

# Step 3: gradle.properties proxy
gp = root / "gradle.properties"
gp_text = gp.read_text(errors="ignore") if gp.exists() else ""
if "systemProp.http.proxyHost" not in gp_text:
    with open(gp, "a") as f:
        f.write(f"\nsystemProp.http.proxyHost={proxy_host}\nsystemProp.http.proxyPort={proxy_port}\nsystemProp.https.proxyHost={proxy_host}\nsystemProp.https.proxyPort={proxy_port}\n")
print(f"[3/9] gradle.properties proxy injected")

# Step 4: Patch wrapper URL
wp = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
wp_text = wp.read_text(errors="replace")
m = re.search(r'(gradle-[\d.]+-(bin|all)\.zip)', wp_text)
if m:
    wp_text = re.sub(r'distributionUrl\s*=\s*.*', f'distributionUrl=https\\://services.gradle.org/distributions/{m.group(1)}', wp_text)
    wp.write_text(wp_text)
print(f"[4/9] distributionUrl → services.gradle.org/{m.group(1)}")

# Step 5: JDK compat
java_cmd = shutil.which("java.exe") or "java"
jver = subprocess.run([java_cmd, "-version"], capture_output=True, text=True, timeout=10)
jdk = int(re.search(r'"(\d+)', jver.stderr+jver.stdout).group(1))
gv = int(re.search(r'gradle-(\d+)', wp_text).group(1))
compat = {6:15, 7:19, 8:21, 9:24}
if jdk > compat.get(gv, 99):
    for jp in (Path.home()/".javaapex"/"jdk-cache"/"jdk11").rglob("java.exe"):
        if "bin" in str(jp):
            java_cmd = str(jp)
            break
    print(f"[5/9] JDK {jdk} too new for Gradle {gv} → using JDK 11: {java_cmd}")
else:
    print(f"[5/9] JDK {jdk} compatible with Gradle {gv}")

# Step 6: spring-core downgrade
orig_java = shutil.which("java.exe") or "java"
if java_cmd != orig_java:
    bg = (root/"build.gradle").read_text(errors="replace")
    if re.search(r'spring-core:6\.\d+', bg):
        bg = re.sub(r'(spring-core:)6\.\d+\.\d+', r'\g<1>5.3.39', bg)
        (root/"build.gradle").write_text(bg)
        print("[6/9] Downgraded spring-core 6.x → 5.3.39")
    else:
        print("[6/9] spring-core already 5.x")
else:
    print("[6/9] spring-core: no change needed")

# Step 7: jakarta.servlet fix
modules_need = []
for bg in root.rglob("build.gradle"):
    if ".gradle" in str(bg.parent): continue
    jsrc = bg.parent/"src"/"main"/"java"
    if not jsrc.exists(): continue
    for jf in jsrc.rglob("*.java"):
        try:
            if "import jakarta.servlet" in jf.read_text(errors="ignore")[:3000]:
                modules_need.append(bg.parent)
                break
        except: continue
if modules_need:
    for mod in modules_need:
        bgp = mod/"build.gradle"
        bt = bgp.read_text(errors="replace")
        if "jakarta.servlet:jakarta.servlet-api" in bt: continue
        bt = bt.replace("javax.servlet:javax.servlet-api", "jakarta.servlet:jakarta.servlet-api")
        if "jakarta.servlet:jakarta.servlet-api" not in bt:
            cfg = "providedCompile" if "apply plugin: 'war'" in bt else "implementation"
            bt += f"\ndependencies {{ {cfg} 'jakarta.servlet:jakarta.servlet-api:5.0.0' }}\n"
        bgp.write_text(bt)
        print(f"[7/9] Added jakarta.servlet-api to {mod.name}")
else:
    print("[7/9] No jakarta.servlet imports → no fix needed")

# Step 8: Compile + auto-fix missing imports
proxy_jvm = [f"-Dhttp.proxyHost={proxy_host}", f"-Dhttp.proxyPort={proxy_port}",
             f"-Dhttps.proxyHost={proxy_host}", f"-Dhttps.proxyPort={proxy_port}",
             "-Dhttp.nonProxyHosts=localhost|127.0.0.1"]
env = os.environ.copy()
env.update({"HTTP_PROXY":f"http://{proxy_host}:{proxy_port}","HTTPS_PROXY":f"http://{proxy_host}:{proxy_port}",
            "ARTIFACTORY_USER":art_user,"ARTIFACTORY_PASSWORD":art_pass})
gradle_base = [java_cmd,*proxy_jvm,"-classpath",str(root/"gradle"/"wrapper"/"gradle-wrapper.jar"),
               "org.gradle.wrapper.GradleWrapperMain","--init-script",str(init_gradle)]

print("[8/9] Compiling...")
r = subprocess.run(gradle_base+["compileJava","-x","test","--stacktrace"], cwd=str(root), capture_output=True, text=True, timeout=300, env=env)

if r.returncode != 0:
    output = r.stdout + r.stderr
    KNOWN = {"Instant":"java.time.Instant","DateTimeFormatter":"java.time.format.DateTimeFormatter",
             "ZoneId":"java.time.ZoneId","ZonedDateTime":"java.time.ZonedDateTime","LocalDate":"java.time.LocalDate",
             "LocalDateTime":"java.time.LocalDateTime","Duration":"java.time.Duration",
             "Collectors":"java.util.stream.Collectors","Stream":"java.util.stream.Stream",
             "Optional":"java.util.Optional","Objects":"java.util.Objects",
             "StandardCharsets":"java.nio.charset.StandardCharsets"}
    
    err_files = {}
    lines = output.split("\n")
    for i, line in enumerate(lines):
        if "cannot find symbol" in line:
            context = "\n".join(lines[max(0,i-1):i+5])
            for sym, imp in KNOWN.items():
                if sym in context:
                    for j in range(i, max(0,i-5), -1):
                        mf = re.match(r'(.+\.java):\d+:', lines[j])
                        if mf:
                            err_files.setdefault(mf.group(1), set()).add(imp)
                            break
    
    fixed = False
    for fpath, imports in err_files.items():
        fp = Path(fpath)
        if not fp.exists(): continue
        src = fp.read_text(errors="replace")
        added = [f"import {imp};" for imp in imports if f"import {imp};" not in src]
        if added:
            last = 0
            for m_imp in re.finditer(r'^import\s+.+;', src, re.MULTILINE):
                last = m_imp.end()
            if last > 0:
                src = src[:last] + "\n" + "\n".join(added) + src[last:]
            else:
                src = "\n".join(added) + "\n" + src
            fp.write_text(src)
            print(f"       Auto-added: {added}")
            fixed = True
    
    if fixed:
        print("       Retrying compile...")
        r = subprocess.run(gradle_base+["compileJava","-x","test"], cwd=str(root), capture_output=True, text=True, timeout=300, env=env)

if r.returncode == 0:
    print("       Compile: SUCCESS")
else:
    errs = [l for l in (r.stdout+r.stderr).split("\n") if "error:" in l.lower()]
    print(f"       Compile: FAILED ({len(errs)} errors) — trying WAR anyway")

# Step 9: Build WAR
print("[9/9] Building WAR...")
r2 = subprocess.run(gradle_base+["war","-x","test"], cwd=str(root), capture_output=True, text=True, timeout=300, env=env)

war_file = None
for d in [root/"PinnacleToolsWAR", root]:
    for w in d.rglob("*.war"):
        ws = str(w).replace("\\","/")
        if "/build/" in ws or "/libs/" in ws:
            war_file = w; break
    if war_file: break
if not war_file:
    for w in root.rglob("*.war"):
        war_file = w; break

print()
print("=" * 70)
if war_file:
    sz = war_file.stat().st_size
    print(f"  ✅ WAR FILE FOUND: {war_file.relative_to(root)}")
    print(f"     Size: {sz:,} bytes ({sz/1024/1024:.1f} MB)")
else:
    print("  ❌ NO WAR FILE FOUND")
    for line in (r2.stdout+r2.stderr).split("\n")[-8:]:
        print(f"     {line.rstrip()}")
print("=" * 70)
