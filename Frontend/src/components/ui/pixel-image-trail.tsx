"use client";

import { cn } from "@/lib/utils";
import * as React from "react";

interface PixelImageTrailProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Image revealed by the pixel trail. */
  src: string;
  /** Accessible description for the image. */
  alt: string;
  /** Width and height of each square in pixels. */
  pixelSize?: number;
  /** Maximum distance for an occasional satellite pixel. */
  radius?: number;
  /** Time in milliseconds before a square completely fades. */
  fadeDuration?: number;
  /** Maximum number of squares kept in the trail. */
  maxPixels?: number;
  /** Number of image fragments visible before the first interaction. */
  initialPixels?: number;
}

interface TrailPixel {
  column: number;
  row: number;
  touchedAt: number;
  ambient: boolean;
}

export function PixelImageTrail({
  src,
  alt,
  pixelSize = 36,
  radius = 58,
  fadeDuration = 900,
  maxPixels = 84,
  initialPixels = 24,
  className,
  children,
  ...props
}: PixelImageTrailProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const imageRef = React.useRef<HTMLImageElement>(null);

  React.useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const image = imageRef.current;
    const context = canvas?.getContext("2d");

    if (!container || !canvas || !image || !context) return;

    const size = Math.max(12, pixelSize);
    const pixels = new Map<string, TrailPixel>();
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    let width = 0;
    let height = 0;
    let frame = 0;
    let pointerInside = false;
    const hoveredKeys = new Set<string>();
    let lastColumn: number | null = null;
    let lastRow: number | null = null;

    const seedPixels = () => {
      const columns = Math.max(1, Math.ceil(width / size));
      const rows = Math.max(1, Math.ceil(height / size));
      const count = Math.min(initialPixels, columns * rows);

      for (let index = 0; index < count; index += 1) {
        const column = Math.floor(Math.random() * columns);
        const row = Math.floor(Math.random() * rows);
        pixels.set(`${column}:${row}`, {
          column,
          row,
          touchedAt: performance.now(),
          ambient: true,
        });
      }
    };

    const resize = () => {
      cancelAnimationFrame(frame);
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);

      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      pixels.clear();
      seedPixels();
      context.clearRect(0, 0, width, height);
      frame = requestAnimationFrame(draw);
    };

    const drawPixel = (pixel: TrailPixel, opacity: number) => {
      if (!image.complete || !image.naturalWidth || !image.naturalHeight) {
        return;
      }

      const x = pixel.column * size;
      const y = pixel.row * size;
      const coverScale = Math.max(
        width / image.naturalWidth,
        height / image.naturalHeight,
      );
      const renderedWidth = image.naturalWidth * coverScale;
      const renderedHeight = image.naturalHeight * coverScale;
      const offsetX = (width - renderedWidth) / 2;
      const offsetY = (height - renderedHeight) / 2;

      context.globalAlpha = opacity;
      context.drawImage(
        image,
        (x - offsetX) / coverScale,
        (y - offsetY) / coverScale,
        size / coverScale,
        size / coverScale,
        x,
        y,
        size,
        size,
      );
    };

    const draw = (now: number) => {
      frame = 0;
      context.clearRect(0, 0, width, height);

      for (const [key, pixel] of pixels) {
        if (pointerInside && hoveredKeys.has(key)) {
          pixel.touchedAt = now;
        }

        const age = now - pixel.touchedAt;
        const opacity = pixel.ambient
          ? pointerInside && hoveredKeys.has(key)
            ? 1
            : 0.58
          : reducedMotion
            ? pointerInside
              ? 1
              : 0
            : Math.max(0, 1 - age / Math.max(120, fadeDuration));

        if (opacity <= 0) {
          pixels.delete(key);
          continue;
        }

        drawPixel(pixel, opacity * opacity * (3 - 2 * opacity));
      }

      context.globalAlpha = 1;
      if (
        !reducedMotion &&
        [...pixels.values()].some((pixel) => !pixel.ambient)
      ) {
        frame = requestAnimationFrame(draw);
      }
    };

    const requestDraw = () => {
      if (!frame) frame = requestAnimationFrame(draw);
    };

    const trimTrail = () => {
      const limit = Math.max(1, maxPixels);
      const trailPixels = [...pixels.entries()].filter(
        ([, pixel]) => !pixel.ambient,
      );
      if (trailPixels.length <= limit) return;

      const oldest = trailPixels.sort(
        (a, b) => a[1].touchedAt - b[1].touchedAt,
      );
      const excess = trailPixels.length - limit;
      for (let index = 0; index < excess; index += 1) {
        const entry = oldest[index];
        if (entry) pixels.delete(entry[0]);
      }
    };

    const setTrailPixel = (
      key: string,
      column: number,
      row: number,
      touchedAt: number,
    ) => {
      if (pixels.get(key)?.ambient) return;
      pixels.set(key, { column, row, touchedAt, ambient: false });
    };

    const paintAt = (clientX: number, clientY: number) => {
      const rect = container.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      const centerColumn = Math.floor(x / size);
      const centerRow = Math.floor(y / size);

      if (reducedMotion) {
        for (const [key, pixel] of pixels) {
          if (!pixel.ambient) pixels.delete(key);
        }
      }

      const now = performance.now();
      hoveredKeys.clear();
      const fromColumn = lastColumn ?? centerColumn;
      const fromRow = lastRow ?? centerRow;
      const columnDistance = centerColumn - fromColumn;
      const rowDistance = centerRow - fromRow;
      const steps = Math.max(
        1,
        Math.abs(columnDistance),
        Math.abs(rowDistance),
      );

      for (let step = 0; step <= steps; step += 1) {
        const progress = step / steps;
        const column = Math.round(fromColumn + columnDistance * progress);
        const row = Math.round(fromRow + rowDistance * progress);
        const key = `${column}:${row}`;

        setTrailPixel(key, column, row, now);
      }

      const xDirection = x % size > size / 2 ? 1 : -1;
      const yDirection = y % size > size / 2 ? 1 : -1;
      const activeCluster: Array<[number, number]> = [
        [centerColumn, centerRow],
        [centerColumn + xDirection, centerRow],
        [centerColumn, centerRow + yDirection],
        [centerColumn + xDirection, centerRow + yDirection],
      ];

      for (const [column, row] of activeCluster) {
        if (
          column < 0 ||
          row < 0 ||
          column * size >= width ||
          row * size >= height
        ) {
          continue;
        }

        const key = `${column}:${row}`;
        hoveredKeys.add(key);
        setTrailPixel(key, column, row, now);
      }

      const moved = lastColumn !== centerColumn || lastRow !== centerRow;
      if (moved && !reducedMotion && Math.random() < 0.34) {
        const spread = Math.max(1, Math.floor(radius / size));
        const distance = 1 + Math.floor(Math.random() * spread);
        const horizontalMotion =
          Math.abs(columnDistance) >= Math.abs(rowDistance);
        const column =
          centerColumn +
          (horizontalMotion ? 0 : Math.random() < 0.5 ? -distance : distance);
        const row =
          centerRow +
          (horizontalMotion ? (Math.random() < 0.5 ? -distance : distance) : 0);

        if (
          column >= 0 &&
          row >= 0 &&
          column * size < width &&
          row * size < height
        ) {
          setTrailPixel(
            `${column}:${row}`,
            column,
            row,
            now - fadeDuration * 0.18,
          );
        }
      }

      lastColumn = centerColumn;
      lastRow = centerRow;

      trimTrail();
      requestDraw();
    };

    const onPointerEnter = (event: PointerEvent) => {
      pointerInside = true;
      paintAt(event.clientX, event.clientY);
    };

    const onPointerMove = (event: PointerEvent) => {
      pointerInside = true;
      paintAt(event.clientX, event.clientY);
    };

    const onPointerLeave = () => {
      pointerInside = false;
      hoveredKeys.clear();
      lastColumn = null;
      lastRow = null;
      if (reducedMotion) {
        for (const [key, pixel] of pixels) {
          if (!pixel.ambient) pixels.delete(key);
        }
        requestDraw();
      }
    };

    const onFocusIn = () => {
      const rect = container.getBoundingClientRect();
      pointerInside = true;
      paintAt(rect.left + rect.width / 2, rect.top + rect.height / 2);
    };

    const onFocusOut = (event: FocusEvent) => {
      if (!container.contains(event.relatedTarget as Node | null)) {
        onPointerLeave();
      }
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    image.addEventListener("load", requestDraw);
    container.addEventListener("pointerenter", onPointerEnter);
    container.addEventListener("pointermove", onPointerMove);
    container.addEventListener("pointerleave", onPointerLeave);
    container.addEventListener("focusin", onFocusIn);
    container.addEventListener("focusout", onFocusOut);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      image.removeEventListener("load", requestDraw);
      container.removeEventListener("pointerenter", onPointerEnter);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("pointerleave", onPointerLeave);
      container.removeEventListener("focusin", onFocusIn);
      container.removeEventListener("focusout", onFocusOut);
    };
  }, [fadeDuration, initialPixels, maxPixels, pixelSize, radius, src]);

  return (
    <div
      ref={containerRef}
      className={cn("relative isolate overflow-hidden touch-pan-y", className)}
      {...props}
    >
      <img
        ref={imageRef}
        src={src}
        alt={alt}
        className="pointer-events-none absolute inset-0 size-full object-cover opacity-0"
        draggable={false}
      />
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 size-full"
      />
      {children ? <div className="relative z-10">{children}</div> : null}
    </div>
  );
}
