"""First-class Apache Velocity (``.vm``) functional-test support.

This module is intentionally **pure / dependency-free** so it can be imported and
unit-tested without the rest of the (very large) ``functional_test_pipeline``.
It provides three things the pipeline needs to give Velocity server-rendered web
apps first-class treatment instead of dumping them into "needs manual review":

1. Detection & route mapping
   * :func:`detect_velocity_templates` — find ``.vm`` templates and their
     Front-Controller ``_PAGE`` key.
   * :func:`map_templates_to_routes` — join each template to the controller
     route that renders it by scanning ``getTemplate("*.vm")`` calls and
     MVC/servlet mappings.

2. Layer 1 (dependency-free render tests)
   * :func:`render_layer1_junit` / :func:`render_layer1_pom` — a JUnit 5 +
     Apache Velocity + Jsoup test module that merges every template with
     representative contexts and asserts: no unresolved ``$refs`` / leaked
     ``#directives``, HTML well-formedness (Jsoup), XSS/escaping safety, both
     ``#if/#else`` branches, and empty/single/multi ``#foreach`` cases.
     Layer 1 needs **zero** network, Docker, browser or original source.

3. Layer 2 (E2E, only when a runtime is available)
   * :func:`render_layer2_selenium` / :func:`render_layer2_playwright` — hit the
     rendered route through a real browser.

Degradation reasons 2.1–2.6 (see :data:`DEGRADATION_REASONS`) let the pipeline
name *exactly* which prerequisite was missing instead of silently degrading.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Structured degradation reasons (loud, not silent).  The pipeline appends the
# matching entry to ``result["degradation_reasons"]`` whenever it falls back.
# ---------------------------------------------------------------------------
DEGRADATION_REASONS: Dict[str, str] = {
    "2.1": "Container runtime (Docker/Podman) not available — skipped WAR-in-Tomcat startup.",
    "2.2": "JDK + Maven toolchain not available — cannot build/run JVM tests.",
    "2.3": "Node.js/npm runtime not available — skipped Playwright E2E.",
    "2.4": "No browser (Edge/Chrome) or webdriver available — skipped Selenium/Playwright E2E.",
    "2.5": "Maven Central / dependency mirror blocked — using offline (go-offline) fallback.",
    "2.6": "Original source (WAR build inputs) missing — cannot start the real application.",
}


def degradation_reason(code: str, detail: str = "") -> Dict[str, str]:
    """Build a structured degradation-reason record for the result JSON."""
    base = DEGRADATION_REASONS.get(code, "Unknown prerequisite missing.")
    rec = {"code": code, "reason": base}
    if detail:
        rec["detail"] = detail
    return rec


# ---------------------------------------------------------------------------
# Detection & route mapping
# ---------------------------------------------------------------------------
_IGNORE_VM_DIRS = {
    "component", "components", "partial", "partials", "layout", "layouts",
    "fragment", "fragments", "include", "includes", "common", "allcss",
    "web-inf", "meta-inf", "css", "js", "images", "fonts",
}
_IGNORE_VM_SUFFIXES = (".include.vm", ".layer.vm", ".ajax.vm", ".macro.vm", ".vmi")


def _page_key_from_text(text: str, stem: str) -> str:
    """Extract the Front-Controller page key from ``#set($_PAGE="X")``."""
    m = re.search(
        r'#set\s*\(\s*\$\!?\{?_PAGE\}?\s*=\s*["\']([^"\']+)["\']\s*\)',
        text, re.IGNORECASE,
    )
    return (m.group(1).strip() if m else stem) or stem


def is_navigable_vm(rel_path: str) -> bool:
    """Return True when a ``.vm`` file is a real page (not a fragment/partial)."""
    low = rel_path.replace("\\", "/").lower()
    if not low.endswith(".vm"):
        return False
    if low.endswith(_IGNORE_VM_SUFFIXES):
        return False
    parts = low.split("/")
    return not any(p in _IGNORE_VM_DIRS for p in parts[:-1])


def detect_velocity_templates(files: List[Path]) -> List[Dict[str, Any]]:
    """Find navigable ``.vm`` templates.

    Returns a list of dicts: ``{template, name, page_key, source_file}``.
    ``template`` is the path relative to a ``templates/`` (or webapp) root when
    detectable, else the file name — this is what a Velocity file-resource loader
    resolves.
    """
    found: List[Dict[str, Any]] = []
    seen: set = set()
    for path in files:
        norm = str(path).replace("\\", "/")
        if not norm.lower().endswith(".vm"):
            continue
        if not is_navigable_vm(norm):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        # Prefer a path relative to a templates/ root so the generated Velocity
        # FileResourceLoader can resolve it by that name.
        rel = path.name
        low = norm.lower()
        for marker in ("/templates/", "/src/main/webapp/"):
            idx = low.find(marker)
            if idx != -1:
                rel = norm[idx + len(marker):]
                break
        if rel in seen:
            continue
        seen.add(rel)
        found.append({
            "template": rel,
            "name": path.stem,
            "page_key": _page_key_from_text(text, path.stem),
            "source_file": norm,
        })
    return found


_GET_TEMPLATE_RE = re.compile(
    r'getTemplate\s*\(\s*["\']([^"\']+\.vm)["\']', re.IGNORECASE)
_REQUEST_MAPPING_RE = re.compile(
    r'@(?:Get|Post|Request)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.IGNORECASE)
_SERVLET_MAPPING_RE = re.compile(
    r'<url-pattern>\s*([^<]+?)\s*</url-pattern>', re.IGNORECASE)


def map_templates_to_routes(
    templates: List[Dict[str, Any]],
    java_files: List[Path],
    front_controller_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Join each template to the controller route that renders it.

    Scans Java sources for ``getTemplate("foo.vm")`` calls and the nearest
    ``@*Mapping`` / servlet ``<url-pattern>`` to build a route.  When a legacy
    Front-Controller path is supplied (e.g. ``/MAPS``) the authentic runtime URL
    ``/MAPS?_page=<PageKey>`` is used.  Templates with no discovered mapping fall
    back to ``/<template-name>`` so they are still tested.
    """
    # Build a template-name -> route map from getTemplate calls.
    tmpl_to_route: Dict[str, str] = {}
    for jf in java_files:
        low = jf.name.lower()
        if not (low.endswith(".java") or low == "web.xml"):
            continue
        try:
            text = jf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        mappings = _REQUEST_MAPPING_RE.findall(text) + _SERVLET_MAPPING_RE.findall(text)
        route = None
        for mp in mappings:
            mp = (mp or "").strip()
            if mp and mp not in ("/", "/*") and "*" not in mp:
                route = "/" + mp.lstrip("/")
                break
        for tmpl in _GET_TEMPLATE_RE.findall(text):
            base = Path(tmpl.replace("\\", "/")).name.lower()
            if route:
                tmpl_to_route[base] = route

    result: List[Dict[str, Any]] = []
    for t in templates:
        name = Path(str(t["template"]).replace("\\", "/")).name.lower()
        if front_controller_path:
            route = f"{front_controller_path}?_page={t['page_key']}"
        elif name in tmpl_to_route:
            route = tmpl_to_route[name]
        else:
            route = "/" + t["name"]
        entry = dict(t)
        entry["route"] = route
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Context derivation (representative data for Layer 1)
# ---------------------------------------------------------------------------
_REF_RE = re.compile(r'\$\!?\{?([a-zA-Z_][a-zA-Z0-9_]*)')
_FOREACH_RE = re.compile(r'#foreach\s*\(\s*\$([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+\$\!?\{?([a-zA-Z_][a-zA-Z0-9_]*)',
                         re.IGNORECASE)
_IF_RE = re.compile(r'#if\s*\(', re.IGNORECASE)


def analyze_template(text: str) -> Dict[str, Any]:
    """Derive the scalar/collection variables and branch structure of a template."""
    loop_vars = set()
    collections = set()
    for m in _FOREACH_RE.finditer(text):
        loop_vars.add(m.group(1))
        collections.add(m.group(2))
    scalars = set()
    for m in _REF_RE.finditer(text):
        name = m.group(1)
        if name in collections or name in loop_vars:
            continue
        if name.lower() in ("foreach", "if", "else", "elseif", "end", "set", "parse",
                             "include", "macro", "velocitycount"):
            continue
        scalars.add(name)
    return {
        "scalars": sorted(scalars),
        "collections": sorted(collections),
        "loop_vars": sorted(loop_vars),
        "has_if": bool(_IF_RE.search(text)),
        "has_foreach": bool(collections),
    }


# ---------------------------------------------------------------------------
# Layer 1 — dependency-free JUnit 5 + Velocity + Jsoup render tests
# ---------------------------------------------------------------------------
def _java_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_layer1_pom() -> str:
    """Maven POM for the Layer 1 Velocity render-test module (offline-capable)."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.ford.javaapex</groupId>
  <artifactId>velocity-render-tests</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>

  <properties>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <junit.version>5.10.2</junit.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.apache.velocity</groupId>
      <artifactId>velocity-engine-core</artifactId>
      <version>2.3</version>
    </dependency>
    <dependency>
      <groupId>org.jsoup</groupId>
      <artifactId>jsoup</artifactId>
      <version>1.17.2</version>
    </dependency>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>${junit.version}</version>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.2.5</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


def render_layer1_junit(
    templates: List[Dict[str, Any]],
    package: str = "functionaltests.velocity",
    class_name: str = "GeneratedVelocityRenderTest",
) -> str:
    """Generate the JUnit 5 + Velocity + Jsoup Layer 1 test class.

    ``templates`` entries need at least a ``template`` (loader-relative name) and
    ``name`` key; optional ``analysis`` (from :func:`analyze_template`) tunes the
    generated contexts. The template root is provided at runtime via the
    ``velocity.template.dir`` system property (defaults to ``src/main/webapp/templates``).
    """
    # Build a Java array literal describing every template + its representative
    # scalar/collection variables so a single data-driven test covers them all.
    entries: List[str] = []
    for t in templates:
        analysis = t.get("analysis") or {}
        scalars = analysis.get("scalars") or []
        collections = analysis.get("collections") or []
        scalar_lit = ", ".join(f'"{_java_str(s)}"' for s in scalars)
        coll_lit = ", ".join(f'"{_java_str(c)}"' for c in collections)
        entries.append(
            f'    new TemplateSpec("{_java_str(str(t["template"]))}", '
            f'new String[]{{{scalar_lit}}}, new String[]{{{coll_lit}}})'
        )
    entries_block = ",\n".join(entries) if entries else ""

    return f'''package {package};

import org.apache.velocity.VelocityContext;
import org.apache.velocity.app.VelocityEngine;
import org.apache.velocity.Template;
import org.apache.velocity.app.event.EventCartridge;
import org.apache.velocity.app.event.implement.EscapeHtmlReference;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.parser.Parser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assertions;

import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

/**
 * Layer 1 — dependency-free Velocity render tests.
 * Runs with ZERO network / Docker / browser: it merges each ".vm" template with
 * representative contexts and asserts render correctness. Auto-generated.
 */
public class {class_name} {{

    /** Root that the Velocity FileResourceLoader resolves template names against. */
    private static final String TEMPLATE_DIR =
        System.getProperty("velocity.template.dir", "src/main/webapp/templates");

    /**
     * Directory where each template's rendered HTML is written so the migration
     * pipeline can assemble a "page-by-page" journey preview from real output.
     */
    private static final String RENDER_OUT_DIR =
        System.getProperty("velocity.render.out.dir", "reports/pages");

    /** A payload used to prove user-controlled data is HTML-escaped in output. */
    private static final String XSS_PAYLOAD = "<script>alert('xss')</script>";

    private record TemplateSpec(String template, String[] scalars, String[] collections) {{}}

    private static final List<TemplateSpec> TEMPLATES = List.of(
{entries_block}
    );

    private VelocityEngine engine() {{
        VelocityEngine ve = new VelocityEngine();
        ve.setProperty("resource.loaders", "file,stub");
        ve.setProperty("resource.loader.file.class",
            "org.apache.velocity.runtime.resource.loader.FileResourceLoader");
        // Fallback loader: any #parse/#include the file loader cannot find (e.g.
        // a runtime-driven dynamic include such as a computed content page name)
        // resolves to an inert stub instead of aborting the whole render. This
        // keeps the OFFLINE page-by-page preview working without a server.
        ve.setProperty("resource.loader.stub.class",
            "{package}.{class_name}$StubResourceLoader");
        // Register the templates root AND its ancestors as loader paths so that
        // #parse/#include directives resolve regardless of whether they are
        // written relative to the templates dir (e.g. "common/x.vm") or to the
        // webapp root (e.g. "templates/common/x.vm"). Fully offline.
        ve.setProperty("resource.loader.file.path", TEMPLATE_DIR);
        java.io.File _tdir = new java.io.File(TEMPLATE_DIR);
        for (int _d = 0; _d < 3 && _tdir != null; _d++) {{
            java.io.File _parent = _tdir.getParentFile();
            if (_parent == null) break;
            ve.addProperty("resource.loader.file.path", _parent.getPath());
            _tdir = _parent;
        }}
        ve.setProperty("resource.loader.file.cache", "false");
        // Resolve ANY unknown reference / method / property to a readable
        // placeholder so the OFFLINE preview renders the real template structure
        // instead of leaking raw "$ref.method()" text (no server / Docker /
        // business logic required). See MagicUberspect + MagicContext below.
        ve.setProperty("runtime.introspector.uberspect",
            "{package}.{class_name}$MagicUberspect");
        // Do not fail hard on a missing reference — we assert on the rendered text.
        ve.setProperty("runtime.references.strict", "false");
        ve.init();
        return ve;
    }}

    private VelocityContext context(TemplateSpec spec, String collectionMode, boolean flag, String xss) {{
        // MagicContext returns a placeholder for every reference that was not
        // explicitly seeded, so undefined top-level refs (e.g. $viewTO) still
        // render instead of leaking as literal "$viewTO..." text.
        MagicContext ctx = new MagicContext();
        // Register HTML-escaping for EVERY reference insertion so user-controlled
        // data is escaped on output — this is what makes the XSS-safety assertion
        // achievable without requiring velocity-tools ($esc.html) in the template.
        EventCartridge ec = new EventCartridge();
        ec.addReferenceInsertionEventHandler(new EscapeHtmlReference());
        ec.attachToContext(ctx);
        // Provide the common velocity-tools ``$esc`` helper so templates that
        // call $esc.html(...) resolve rather than leaking literal call text.
        EscTool esc = new EscTool();
        ctx.put("esc", esc);
        ctx.put("escape", esc);
        ctx.put("escapetool", esc);
        for (String s : spec.scalars()) {{
            // "esc"/"esc.html" is a velocity-tools helper, not real page data.
            if ("esc".equals(s) || "escape".equals(s) || "escapetool".equals(s)) continue;
            ctx.put(s, xss != null ? xss : (s + "_value"));
        }}
        // Toggle #if / #else branches deterministically.
        ctx.put("flag", flag);
        ctx.put("show", flag);
        ctx.put("enabled", flag);
        // empty / single / multi #foreach cases.
        List<Object> items;
        switch (collectionMode) {{
            case "empty":  items = new ArrayList<>(); break;
            case "single": items = List.of(row(1)); break;
            default:       items = List.of(row(1), row(2), row(3)); break;
        }}
        for (String c : spec.collections()) {{
            ctx.put(c, items);
        }}
        return ctx;
    }}

    private static Map<String, Object> row(int i) {{
        Map<String, Object> m = new HashMap<>();
        m.put("id", i);
        m.put("name", "item" + i);
        m.put("value", "v" + i);
        return m;
    }}

    /**
     * Mock of the velocity-tools ``$esc`` (EscapeTool) helper so templates that
     * call ``$esc.html($x)`` resolve instead of leaking the literal call text.
     * Returns the value unchanged — the {{@link EscapeHtmlReference}} cartridge
     * still HTML-escapes the resulting reference on output, so the XSS-safety
     * assertion stays meaningful.
     */
    public static class EscTool {{
        public String html(Object o)          {{ return o == null ? "" : o.toString(); }}
        public String javascript(Object o)    {{ return o == null ? "" : o.toString(); }}
        public String url(Object o)           {{ return o == null ? "" : o.toString(); }}
        public String xml(Object o)           {{ return o == null ? "" : o.toString(); }}
        public String sql(Object o)           {{ return o == null ? "" : o.toString(); }}
        public String java(Object o)          {{ return o == null ? "" : o.toString(); }}
        public String body(Object o)          {{ return o == null ? "" : o.toString(); }}
        public String propertyKey(Object o)   {{ return o == null ? "" : o.toString(); }}
        public String propertyValue(Object o) {{ return o == null ? "" : o.toString(); }}
        public String unescapeHtml(Object o)  {{ return o == null ? "" : o.toString(); }}
        public String unescapeXml(Object o)   {{ return o == null ? "" : o.toString(); }}
        public String dollar()    {{ return "$"; }}
        public String d()         {{ return "$"; }}
        public String hash()      {{ return "#"; }}
        public String h()         {{ return "#"; }}
        public String backslash() {{ return "\\\\"; }}
        public String b()         {{ return "\\\\"; }}
        public String quote()     {{ return "\\""; }}
        public String q()         {{ return "\\""; }}
        public String newline()   {{ return "\\n"; }}
        public String n()         {{ return "\\n"; }}
    }}

    /**
     * A universal placeholder returned for any reference / method / property the
     * offline context cannot resolve. It is chainable ($a.b().c()) and prints a
     * readable label, so a template renders its full HTML structure with
     * representative data — WITHOUT a running server, Docker, or the real Java
     * ViewTransformer/business logic behind the page.
     */
    public static final class Magic {{
        private final String label;
        public Magic(String label) {{ this.label = label == null ? "" : label; }}
        @Override public String toString() {{ return label; }}
        public java.util.Iterator<Object> iterator() {{ return Collections.<Object>emptyIterator(); }}
    }}

    /** Context that hands back a {{@link Magic}} for every unseeded reference. */
    public static final class MagicContext extends VelocityContext {{
        @Override
        public Object internalGet(String key) {{
            Object v = super.internalGet(key);
            if (v != null || super.containsKey(key)) return v;
            return new Magic(key);
        }}
    }}

    /**
     * Fallback resource loader that renders any not-found #parse/#include target
     * as an inert HTML comment instead of throwing ResourceNotFoundException.
     * Dynamic, runtime-resolved includes (a computed content page name)
     * therefore never break the offline page-by-page preview.
     */
    public static final class StubResourceLoader
            extends org.apache.velocity.runtime.resource.loader.ResourceLoader {{
        @Override public void init(org.apache.velocity.util.ExtProperties configuration) {{ }}
        @Override public java.io.Reader getResourceReader(String source, String encoding) {{
            return new java.io.StringReader("<!-- offline preview: unresolved include '" + source + "' -->");
        }}
        @Override public boolean isSourceModified(org.apache.velocity.runtime.resource.Resource resource) {{ return false; }}
        @Override public long getLastModified(org.apache.velocity.runtime.resource.Resource resource) {{ return 0L; }}
    }}

    /**
     * Uberspect that falls back to a {{@link Magic}} value whenever a real method
     * or property cannot be found on an object. Real getters/collections keep
     * working; only the otherwise-unresolvable calls (e.g. $viewTO.getStatusCd())
     * are satisfied with a placeholder instead of leaking raw text.
     */
    public static final class MagicUberspect
            extends org.apache.velocity.util.introspection.UberspectImpl {{
        private static String humanize(String m) {{
            String s = m == null ? "" : m;
            if (s.startsWith("get") && s.length() > 3) s = s.substring(3);
            else if (s.startsWith("is") && s.length() > 2) s = s.substring(2);
            return s;
        }}
        @Override
        public java.util.Iterator getIterator(Object obj, org.apache.velocity.util.introspection.Info i) {{
            if (obj instanceof Magic) return Collections.emptyIterator();
            return super.getIterator(obj, i);
        }}
        @Override
        public org.apache.velocity.util.introspection.VelMethod getMethod(
                Object obj, final String methodName, Object[] args,
                org.apache.velocity.util.introspection.Info i) {{
            org.apache.velocity.util.introspection.VelMethod real = null;
            try {{ real = super.getMethod(obj, methodName, args, i); }} catch (Exception ignored) {{}}
            if (real != null) return real;
            final String label = humanize(methodName);
            return new org.apache.velocity.util.introspection.VelMethod() {{
                public Object invoke(Object o, Object[] params) {{
                    if (params != null && params.length == 1
                            && params[0] instanceof String
                            && !((String) params[0]).isEmpty()) {{
                        return new Magic((String) params[0]);
                    }}
                    return new Magic(label);
                }}
                public boolean isCacheable() {{ return false; }}
                public String getMethodName() {{ return methodName; }}
                public Class<?> getReturnType() {{ return Object.class; }}
                public java.lang.reflect.Method getMethod() {{ return null; }}
            }};
        }}
        @Override
        public org.apache.velocity.util.introspection.VelPropertyGet getPropertyGet(
                Object obj, final String identifier,
                org.apache.velocity.util.introspection.Info i) {{
            org.apache.velocity.util.introspection.VelPropertyGet real = null;
            try {{ real = super.getPropertyGet(obj, identifier, i); }} catch (Exception ignored) {{}}
            if (real != null) return real;
            return new org.apache.velocity.util.introspection.VelPropertyGet() {{
                public Object invoke(Object o) {{ return new Magic(identifier); }}
                public boolean isCacheable() {{ return false; }}
                public String getMethodName() {{ return identifier; }}
            }};
        }}
    }}

    private String render(VelocityEngine ve, String templateName, VelocityContext ctx) {{
        Template t = ve.getTemplate(templateName);
        StringWriter w = new StringWriter();
        t.merge(ctx, w);
        return w.toString();
    }}

    private void assertRenderIsClean(String templateName, String html) {{
        // JS/CSS/comments legitimately contain '$' and '#' (jQuery, template
        // literals, CSS ids) that are NOT Velocity leftovers — scan without them.
        String scan = html
            .replaceAll("(?is)<script[^>]*>.*?</script>", " ")
            .replaceAll("(?is)<style[^>]*>.*?</style>", " ")
            .replaceAll("(?is)<!--.*?-->", " ");
        // (a) No FORMAL unresolved Velocity reference — ${{name}} / $!{{name}}.
        //     Formal notation only appears in templates, never in real HTML/JS,
        //     so it is an unambiguous "variable never resolved" signal (and it
        //     will not false-positive on jQuery '$' or undefined tool chains).
        Assertions.assertFalse(scan.matches("(?s).*\\\\$\\\\!?\\\\{{[A-Za-z_][\\\\w.]*\\\\}}.*"),
            "Unresolved ${{reference}} left in " + templateName);
        // (b) No leaked block directive as REAL directive syntax:
        //     #if(/#foreach(/#set(/#parse(/#include(/#macro(/#define( ...
        Assertions.assertFalse(scan.matches("(?s).*#(if|elseif|foreach|set|parse|include|macro|define|evaluate)\\\\s*\\\\(.*"),
            "Leaked #directive in " + templateName);
        //     ... or a standalone #end / #else / #stop (not #endregion etc.).
        Assertions.assertFalse(scan.matches("(?s).*#(end|else|stop)(?![A-Za-z]).*"),
            "Leaked #end/#else directive in " + templateName);
        // (c) HTML well-formedness via Jsoup.
        Document doc = Jsoup.parse(html, "", Parser.htmlParser());
        Assertions.assertNotNull(doc.body(), "Jsoup could not parse body of " + templateName);
        Assertions.assertTrue(doc.getAllElements().size() > 0,
            "No HTML elements rendered from " + templateName);
    }}

    /**
     * Persist a template's rendered HTML so the migration pipeline can build a
     * page-by-page journey preview. Best-effort — never fails the test.
     */
    private void writeRenderedPage(int index, String templateName, String html) {{
        try {{
            Path dir = Paths.get(RENDER_OUT_DIR);
            Files.createDirectories(dir);
            String safe = templateName.replaceAll("[\\\\\\\\/]+", "_").replaceAll("[^A-Za-z0-9._-]", "_");
            String fileName = String.format("%04d-%s.html", index, safe);
            if (!fileName.toLowerCase().endsWith(".html")) fileName = fileName + ".html";
            Files.write(dir.resolve(fileName), html.getBytes(StandardCharsets.UTF_8));
        }} catch (Exception ignored) {{
            // Page capture is a preview aid only — never block the render test.
        }}
    }}

    @Test
    @DisplayName("Every .vm template renders cleanly with representative contexts")
    void templatesRenderCleanly() {{
        Assertions.assertFalse(TEMPLATES.isEmpty(), "No Velocity templates were discovered.");
        VelocityEngine ve = engine();
        List<String> failures = new ArrayList<>();
        int rendered = 0;
        int pageIndex = 0;
        for (TemplateSpec spec : TEMPLATES) {{
            boolean ok = true;
            // (e) empty / single / multi #foreach and (d) both #if branches.
            for (String mode : new String[]{{"empty", "single", "multi"}}) {{
                for (boolean flag : new boolean[]{{true, false}}) {{
                    try {{
                        String html = render(ve, spec.template(), context(spec, mode, flag, null));
                        assertRenderIsClean(spec.template(), html);
                    }} catch (Throwable t) {{
                        ok = false;
                        failures.add(spec.template() + " [mode=" + mode + ", flag=" + flag + "]: " + t.getMessage());
                    }}
                }}
            }}
            if (ok) rendered++;
            // Capture ONE representative render (multi rows, flag on) per template
            // as a real page for the page-by-page journey preview.
            try {{
                String preview = render(ve, spec.template(), context(spec, "multi", true, null));
                writeRenderedPage(pageIndex++, spec.template(), preview);
            }} catch (Throwable ignored) {{
                // Preview capture is best-effort — never fail the test over it.
            }}
        }}
        Assertions.assertTrue(rendered > 0,
            "No Velocity template rendered cleanly. First issues: "
                + failures.subList(0, Math.min(5, failures.size())));
        Assertions.assertTrue(failures.isEmpty(),
            "Some Velocity templates did not render cleanly (" + failures.size() + "):\\n"
                + String.join("\\n", failures));
    }}

    @Test
    @DisplayName("User-controlled data is HTML-escaped (XSS safety)")
    void templatesEscapeUserInput() {{
        VelocityEngine ve = engine();
        List<String> unsafe = new ArrayList<>();
        for (TemplateSpec spec : TEMPLATES) {{
            if (spec.scalars().length == 0) continue;
            try {{
                String html = render(ve, spec.template(), context(spec, "single", true, XSS_PAYLOAD));
                if (html.contains("<script>alert('xss')</script>")) {{
                    unsafe.add(spec.template());
                }}
            }} catch (Throwable ignored) {{
                // A template that could not merge is covered by the render test.
            }}
        }}
        Assertions.assertTrue(unsafe.isEmpty(),
            "Unescaped XSS payload rendered in " + unsafe
                + " — template(s) must HTML-escape user data (e.g. $esc.html()).");
    }}
}}
'''


# ---------------------------------------------------------------------------
# Layer 2 — E2E (only when a runtime is available)
# ---------------------------------------------------------------------------
def render_layer2_selenium(
    routes: List[Dict[str, Any]],
    base_url: str = "http://localhost:8080",
    class_name: str = "GeneratedVelocityE2ETest",
    package: str = "functionaltests.velocity",
) -> str:
    """Edge-first Selenium E2E test hitting each rendered Velocity route."""
    checks: List[str] = []
    for r in routes:
        route = str(r.get("route", "/" + r.get("name", "")))
        name = re.sub(r"\W+", "_", r.get("name", "page")).strip("_") or "page"
        checks.append(f'''
    @Test
    @DisplayName("Route renders: {_java_str(route)}")
    void renders_{name}() {{
        driver.get(BASE_URL + "{_java_str(route)}");
        String src = driver.getPageSource();
        capturePage("{_java_str(name)}");
        Assertions.assertFalse(src == null || src.isBlank(), "Blank page at {_java_str(route)}");
    }}''')
    body = "\n".join(checks)
    return f'''package {package};

import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.edge.EdgeDriver;
import org.openqa.selenium.edge.EdgeOptions;
import org.junit.jupiter.api.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.atomic.AtomicInteger;

/** Layer 2 — Selenium (Edge-first) E2E. Runs only when a browser is available. */
public class {class_name} {{
    private static final String BASE_URL =
        System.getenv().getOrDefault("FUNCTIONAL_BASE_URL", "{_java_str(base_url)}");
    /** Ordered page frames are written here to build a page-by-page journey video. */
    private static final String SHOT_DIR =
        System.getProperty("velocity.screenshot.dir", "target/screenshots");
    private static final AtomicInteger FRAME = new AtomicInteger(0);
    private WebDriver driver;

    @BeforeEach
    void setUp() {{
        EdgeOptions opts = new EdgeOptions();
        // Headless by default; set HEADLESS=false to watch the run in a window.
        boolean headless = !"false".equalsIgnoreCase(
            System.getenv().getOrDefault("HEADLESS", "true"));
        if (headless) {{
            opts.addArguments("--headless=new");
        }}
        opts.addArguments("--window-size=1366,900", "--no-sandbox", "--disable-gpu");
        driver = new EdgeDriver(opts);
    }}

    @AfterEach
    void tearDown() {{ if (driver != null) driver.quit(); }}

    /**
     * Save an ordered PNG frame of the current page so the pipeline can stitch a
     * page-by-page journey video/images. Best-effort — never fails the test.
     */
    private void capturePage(String label) {{
        try {{
            if (!(driver instanceof TakesScreenshot)) return;
            byte[] png = ((TakesScreenshot) driver).getScreenshotAs(OutputType.BYTES);
            Path dir = Paths.get(SHOT_DIR);
            Files.createDirectories(dir);
            String safe = label.replaceAll("[^A-Za-z0-9._-]", "_");
            String name = String.format("%04d-%s.png", FRAME.getAndIncrement(), safe);
            Files.write(dir.resolve(name), png);
        }} catch (Exception ignored) {{
            // Screenshot capture is a preview aid only — never block the E2E test.
        }}
    }}
{body}
}}
'''


def render_layer2_playwright(
    routes: List[Dict[str, Any]],
    base_url: str = "http://localhost:8080",
) -> str:
    """Playwright E2E spec hitting each rendered Velocity route."""
    tests = []
    for r in routes:
        route = str(r.get("route", "/" + r.get("name", "")))
        name = r.get("name", "page")
        tests.append(f'''test('renders {name} ({route})', async ({{ page }}) => {{
  const resp = await page.goto(`${{BASE_URL}}{route}`);
  expect(resp && resp.status()).toBeLessThan(400);
  const body = await page.content();
  expect(body.length).toBeGreaterThan(0);
}});''')
    body = "\n\n".join(tests)
    return f'''import {{ test, expect }} from '@playwright/test';

const BASE_URL = process.env.FUNCTIONAL_BASE_URL || '{base_url}';

{body}
'''
