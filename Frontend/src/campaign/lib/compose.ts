import { formatIsoDate, offerHeadline } from "./format";
import type { OfferFacts } from "./types";
import { timingLine, type OfferWindow } from "./window";

export type OverlayKind = "poster" | "post" | "story";

export const OVERLAY_SIZE: Record<OverlayKind, { w: number; h: number; bandRatio: number }> = {
  poster: { w: 1080, h: 1440, bandRatio: 0.36 },
  post: { w: 1080, h: 1350, bandRatio: 0.3 },
  story: { w: 1080, h: 1920, bandRatio: 0.26 },
};

export type OverlaySpec = {
  kind: OverlayKind;
  headline: string;
  subline: string;
  business: string;
  facts: OfferFacts;
  window?: OfferWindow | null;
  lang: string;
};

const SERIF = '"Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
const INK = "#1f1a14";
const PAPER = "#f3efe6";
const MARIGOLD = "#f0b429";

export function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("The image could not be loaded."));
    img.src = url;
  });
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines;
}

// Largest font size (<= max) at which the text fits in maxLines.
function fitText(ctx: CanvasRenderingContext2D, text: string, weight: string, family: string, max: number, min: number, width: number, maxLines: number) {
  let size = max;
  while (size > min) {
    ctx.font = `${weight} ${size}px ${family}`;
    if (wrap(ctx, text, width).length <= maxLines) break;
    size -= 4;
  }
  ctx.font = `${weight} ${size}px ${family}`;
  return { size, lines: wrap(ctx, text, width).slice(0, maxLines) };
}

export function dateLine(dates: string[], lang: string) {
  if (!dates.length) return "";
  const fmt = (d: string) => formatIsoDate(d, lang, { weekday: "short", day: "numeric", month: "short", year: undefined });
  if (dates.length <= 3) return dates.map(fmt).join(", ");
  return `${fmt(dates[0])} - ${fmt(dates[dates.length - 1])}`;
}

export function factLines(facts: OfferFacts, lang: string, window?: OfferWindow | null) {
  return {
    offer: offerHeadline(facts).toUpperCase(),
    item: facts.item,
    dates: dateLine(facts.dates, lang),
    // The timing row comes from the parsed offer window, in the poster's language. If the times could not be parsed it keeps
    // the owner's own words rather than guessing.
    timings: timingLine(window, lang) || facts.timings || "",
    terms: facts.terms || "",
  };
}

export function drawOverlay(canvas: HTMLCanvasElement, image: HTMLImageElement | null, spec: OverlaySpec) {
  const { w, h, bandRatio } = OVERLAY_SIZE[spec.kind];
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const pad = 64;
  const bandH = Math.round(h * bandRatio);
  const imgH = h - bandH;

  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, w, h);

  if (image) {
    const scale = Math.max(w / image.naturalWidth, imgH / image.naturalHeight);
    const dw = image.naturalWidth * scale;
    const dh = image.naturalHeight * scale;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, w, imgH);
    ctx.clip();
    ctx.drawImage(image, (w - dw) / 2, (imgH - dh) / 2, dw, dh);
    ctx.restore();
  } else {
    ctx.fillStyle = "#e7e0d4";
    ctx.fillRect(0, 0, w, imgH);
  }

  // Scrim behind the headline so it reads on any photo.
  if (spec.headline && spec.kind !== "post") {
    const grad = ctx.createLinearGradient(0, 0, 0, imgH * 0.72);
    grad.addColorStop(0, "rgba(31,26,20,0.9)");
    grad.addColorStop(1, "rgba(31,26,20,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, imgH * 0.72);

    ctx.fillStyle = PAPER;
    ctx.textBaseline = "top";
    ctx.font = `600 26px ${MONO}`;
    ctx.fillText(spec.business.toUpperCase(), pad, pad);
    const head = fitText(ctx, spec.headline, "700", SERIF, spec.kind === "story" ? 112 : 96, 48, w - pad * 2, 3);
    head.lines.forEach((line, i) => ctx.fillText(line, pad, pad + 56 + i * head.size * 1.08));
    if (spec.subline) {
      ctx.font = `500 ${spec.kind === "story" ? 46 : 40}px ${SERIF}`;
      const y = pad + 56 + head.lines.length * head.size * 1.08 + 16;
      wrap(ctx, spec.subline, w - pad * 2).slice(0, 3).forEach((line, i) => ctx.fillText(line, pad, y + i * 58));
    }
  }

  // Facts band: opaque, so contrast never depends on the photo.
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, imgH, w, bandH);
  ctx.fillStyle = INK;
  ctx.fillRect(0, imgH, w, 6);

  const f = factLines(spec.facts, spec.lang, spec.window);
  let y = imgH + 40;
  ctx.textBaseline = "top";
  if (f.offer) {
    ctx.font = `700 88px ${SERIF}`;
    const tw = ctx.measureText(f.offer).width;
    ctx.fillStyle = MARIGOLD;
    ctx.fillRect(pad, y, tw + 48, 120);
    ctx.strokeStyle = INK;
    ctx.lineWidth = 4;
    ctx.strokeRect(pad, y, tw + 48, 120);
    ctx.fillStyle = INK;
    ctx.fillText(f.offer, pad + 24, y + 14);
    ctx.font = `600 64px ${SERIF}`;
    const itemFit = fitText(ctx, f.item, "600", SERIF, 64, 32, w - pad * 2 - tw - 80, 1);
    ctx.fillText(itemFit.lines[0] || "", pad + tw + 76, y + 26);
    y += 148;
  } else {
    const itemFit = fitText(ctx, f.item, "700", SERIF, 60, 32, w - pad * 2, 2);
    itemFit.lines.forEach((line, i) => ctx.fillText(line, pad, y + i * itemFit.size * 1.1));
    y += itemFit.lines.length * itemFit.size * 1.1 + 20;
  }
  const rows = [f.dates, f.timings, f.terms].filter(Boolean);
  const bottom = imgH + bandH - 28;
  const lineH = 62;
  rows.forEach((row) => {
    if (y + lineH > bottom) return;
    ctx.font = `500 48px ${SERIF}`;
    ctx.fillStyle = INK;
    const first = wrap(ctx, row, w - pad * 2)[0] || "";
    ctx.fillText(first, pad, y);
    y += lineH;
  });
}

export function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("The picture could not be exported."))), "image/png"),
  );
}


export function drawStaticReel(canvas: HTMLCanvasElement, image: HTMLImageElement, facts: OfferFacts, business: string, lang: string, sample: boolean) {
  canvas.width = 1280;
  canvas.height = 720;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("The frame could not be rendered.");
  ctx.fillStyle = PAPER;
  ctx.fillRect(0, 0, 1280, 720);
  const photoWidth = 760;
  const scale = Math.max(photoWidth / image.naturalWidth, 720 / image.naturalHeight);
  ctx.save();
  ctx.beginPath();ctx.rect(0,0,photoWidth,720);ctx.clip();
  ctx.drawImage(image,(photoWidth-image.naturalWidth*scale)/2,(720-image.naturalHeight*scale)/2,image.naturalWidth*scale,image.naturalHeight*scale);
  ctx.restore();
  ctx.fillStyle = INK;
  ctx.textBaseline = "top";
  let y = 44;
  const f = factLines(facts,lang);
  const rows = [sample ? "SAMPLE DEMO" : "", business, f.item, f.offer, f.dates, f.timings, f.terms].filter(Boolean);
  for (const row of rows) {
    const fit = fitText(ctx,row,"500",SERIF,28,16,440,4);
    if (wrap(ctx,row,440).length > 4 || fit.lines.some(line => ctx.measureText(line).width > 440)) throw new Error("Offer details do not fit. Shorten the saved details before rendering.");
    const lineHeight = fit.size * 1.2;
    for (const line of fit.lines) {
      if (y + lineHeight > 690) throw new Error("Offer details do not fit. Shorten the saved details before rendering.");
      ctx.fillText(line,800,y);y += lineHeight;
    }
    y += 18;
  }
}
