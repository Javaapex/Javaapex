import type { jsPDF } from "jspdf";

let html2CanvasPromise: Promise<typeof import("html2canvas")["default"]> | null = null;
let jsPdfPromise: Promise<typeof import("jspdf")["jsPDF"]> | null = null;

const loadHtml2Canvas = async () => {
  if (!html2CanvasPromise) {
    html2CanvasPromise = import("html2canvas").then((module) => module.default);
  }

  return html2CanvasPromise;
};

const loadJsPdf = async () => {
  if (!jsPdfPromise) {
    jsPdfPromise = import("jspdf").then((module) => module.jsPDF);
  }

  return jsPdfPromise;
};

export const triggerBlobDownload = (blob: Blob, filename: string) => {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
};

export const cloneBlob = (blob: Blob) => blob.slice(0, blob.size, blob.type || "application/octet-stream");

export const buildHtmlFilename = (filename: string | undefined, fallbackRepoName: string) => {
  const normalizedFallbackRepoName = (fallbackRepoName.trim() || "repository").toUpperCase();
  const fallbackName = `${normalizedFallbackRepoName}-TECHNICAL-DOCUMENT.html`;
  const safeName = (filename?.trim() || fallbackName).replace(/[\\/:*?"<>|]+/g, "-");
  const withoutExtension = safeName.replace(/\.[^.]+$/, "");
  return `${withoutExtension}.html`;
};

export const downloadHtmlDocument = async (html: string, filename: string) => {
  const htmlBlob = new Blob([html], { type: "text/html;charset=utf-8" });
  triggerBlobDownload(htmlBlob, filename);
};

const extractRenderableHtml = (html: string) => {
  const parsedDocument = new DOMParser().parseFromString(html, "text/html");
  const headMarkup = Array.from(
    parsedDocument.head.querySelectorAll("style, link[rel='stylesheet']")
  )
    .map((node) => node.outerHTML)
    .join("");

  return {
    bodyClassName: parsedDocument.body.className,
    markup: `${headMarkup}${parsedDocument.body.innerHTML || html}`,
  };
};

const waitForDocumentAssets = async (container: HTMLElement) => {
  const imagePromises = Array.from(container.querySelectorAll("img")).map(
    (image) =>
      new Promise<void>((resolve) => {
        if (image.complete) {
          resolve();
          return;
        }

        image.addEventListener("load", () => resolve(), { once: true });
        image.addEventListener("error", () => resolve(), { once: true });
      })
  );

  if ("fonts" in document) {
    await (document as Document & { fonts?: FontFaceSet }).fonts?.ready?.catch(() => undefined);
  }

  await Promise.all(imagePromises);
  await new Promise((resolve) => window.setTimeout(resolve, 250));
};

const addPdfLinksForPage = (
  pdf: jsPDF,
  pageElement: HTMLElement,
  pdfWidth: number,
  pdfHeight: number,
  pageIdToPdfPageNumber: Map<string, number>
) => {
  const pageRect = pageElement.getBoundingClientRect();
  if (!pageRect.width || !pageRect.height) {
    return;
  }

  const anchors = Array.from(pageElement.querySelectorAll<HTMLAnchorElement>("a[href]"));

  anchors.forEach((anchor) => {
    const href = anchor.getAttribute("href")?.trim();
    if (!href) {
      return;
    }

    const targetPageNumber = href.startsWith("#")
      ? pageIdToPdfPageNumber.get(href.slice(1))
      : undefined;
    const isExternal = /^https?:\/\//i.test(href);

    if (!targetPageNumber && !isExternal) {
      return;
    }

    Array.from(anchor.getClientRects()).forEach((rect) => {
      const widthRatio = pdfWidth / pageRect.width;
      const heightRatio = pdfHeight / pageRect.height;
      const x = (rect.left - pageRect.left) * widthRatio;
      const y = (rect.top - pageRect.top) * heightRatio;
      const w = Math.max(rect.width * widthRatio, 2);
      const h = Math.max(rect.height * heightRatio, 2);

      if (targetPageNumber) {
        pdf.link(x, y, w, h, { pageNumber: targetPageNumber });
      } else if (isExternal) {
        pdf.link(x, y, w, h, { url: href });
      }
    });
  });
};

export const renderHtmlToPdfBlob = async (html: string) => {
  const [JsPdf, html2canvas] = await Promise.all([loadJsPdf(), loadHtml2Canvas()]);
  const pdf = new JsPdf({
    orientation: "portrait",
    unit: "pt",
    format: "a4",
    compress: true,
  });
  const pdfWidth = pdf.internal.pageSize.getWidth();
  const pdfHeight = pdf.internal.pageSize.getHeight();
  const renderRoot = document.createElement("div");
  const { bodyClassName, markup } = extractRenderableHtml(html);

  renderRoot.className = bodyClassName;
  renderRoot.innerHTML = markup;
  Object.assign(renderRoot.style, {
    position: "fixed",
    left: "-10000px",
    top: "0",
    width: "794px",
    background: "#ffffff",
    zIndex: "-1",
    overflow: "hidden",
  });

  document.body.appendChild(renderRoot);

  try {
    await waitForDocumentAssets(renderRoot);

    const pageElements = Array.from(renderRoot.querySelectorAll<HTMLElement>(".page"));
    const pageIdToPdfPageNumber = new Map<string, number>();

    pageElements.forEach((pageElement, index) => {
      if (pageElement.id) {
        pageIdToPdfPageNumber.set(pageElement.id, index + 1);
      }
    });

    if (pageElements.length > 0) {
      for (const [index, pageElement] of pageElements.entries()) {
        const canvas = await html2canvas(pageElement, {
          backgroundColor: "#ffffff",
          scale: 1.8,
          useCORS: true,
          windowWidth: pageElement.scrollWidth,
          windowHeight: pageElement.scrollHeight,
        });

        if (index > 0) {
          pdf.addPage();
        }

        pdf.addImage(
          canvas.toDataURL("image/png"),
          "PNG",
          0,
          0,
          pdfWidth,
          pdfHeight,
          undefined,
          "FAST"
        );

        addPdfLinksForPage(pdf, pageElement, pdfWidth, pdfHeight, pageIdToPdfPageNumber);
      }
    } else {
      const canvas = await html2canvas(renderRoot, {
        backgroundColor: "#ffffff",
        scale: 1.5,
        useCORS: true,
        windowWidth: renderRoot.scrollWidth,
        windowHeight: renderRoot.scrollHeight,
      });
      const imageData = canvas.toDataURL("image/png");
      const imageHeight = (canvas.height * pdfWidth) / canvas.width;
      let heightLeft = imageHeight;
      let position = 0;

      pdf.addImage(imageData, "PNG", 0, position, pdfWidth, imageHeight, undefined, "FAST");
      heightLeft -= pdfHeight;

      while (heightLeft > 0) {
        position = heightLeft - imageHeight;
        pdf.addPage();
        pdf.addImage(imageData, "PNG", 0, position, pdfWidth, imageHeight, undefined, "FAST");
        heightLeft -= pdfHeight;
      }
    }

    return pdf.output("blob");
  } finally {
    renderRoot.remove();
  }
};

export const downloadHtmlAsPdf = async (html: string, filename: string) => {
  const pdfBlob = await renderHtmlToPdfBlob(html);
  triggerBlobDownload(pdfBlob, filename);
};
