/** Картинка перед загрузкой: какую часть показывать и в каком масштабе.
 *
 *  Фото с телефона почти никогда не совпадает с плиткой: товар оказывался
 *  у края, а на квадратной плитке каталога от него оставалась половина.
 *  Теперь снимок двигают пальцем в рамке той формы, в какой его увидят, и
 *  увеличивают двумя пальцами, колесом или ползунком. Сохраняется ровно то,
 *  что в рамке, — и заодно файл становится в разы меньше телефонного.
 *
 *  Окно во весь экран, а не шторка: перетаскивание в шторке её закрывает.
 *  Пока оно открыто, вертикальный свайп MAX удержан — иначе жест вниз по
 *  снимку сворачивал бы всё приложение.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { haptic, holdVerticalSwipes } from "../lib/bridge";
import { chipClass } from "./Chip";

export type ImageShape = "square" | "cover" | "logo";

/** Ширина к высоте: плитка товара — квадрат, фото витрины — полоса 16:7. */
const RATIO: Record<ImageShape, number> = { square: 1, cover: 16 / 7, logo: 1 };
/** Ширина готовой картинки: больше не нужно ни одному экрану. */
const OUTPUT: Record<ImageShape, number> = { square: 900, cover: 1400, logo: 512 };
/** Во сколько раз можно увеличить сверх «заполнить рамку». */
const ZOOM = 4;

interface Frame {
  width: number;
  height: number;
}

interface View {
  scale: number;
  x: number;
  y: number;
}

/** Выбор картинки: подпись-кнопка со скрытым полем файла внутри. Метка, а
 *  не программный щелчок по полю: так выбор файла открывается и в вебвью. */
export function PickImage({
  onPick,
  className = "",
  label,
  children,
}: {
  onPick: (file: File) => void;
  className?: string;
  /** Для озвучки, если внутри только картинка */
  label?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`cursor-pointer ${className}`} aria-label={label}>
      {children}
      <input
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onPick(file);
        }}
      />
    </label>
  );
}

/** Кнопка-чип «Загрузить фото» тем же видом, что и соседние «Убрать…». */
export function PickChip({
  onPick,
  busy = false,
  children,
}: {
  onPick: (file: File) => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  return (
    <PickImage onPick={onPick} className={chipClass("accent")}>
      {busy ? "Загружаю…" : children}
    </PickImage>
  );
}

/** Выбрал файл → кадрирование → `save` получает готовую картинку.
 *
 *  Ошибка сохранения остаётся в окне: человек видит причину и повторяет,
 *  не выбирая снимок заново. Удалось — вызывающий получает `note`. */
export function useImagePick(
  shape: ImageShape,
  save: (image: Blob) => Promise<void>,
  saved?: string,
) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const pick = useCallback((next: File) => {
    setNote(null);
    setFile(next);
  }, []);

  const dialog = (
    <ImageCrop
      file={file}
      shape={shape}
      busy={busy}
      onCancel={() => setFile(null)}
      onSave={async (image) => {
        setBusy(true);
        try {
          await save(image);
          haptic("success");
          setFile(null);
          if (saved) setNote(saved);
        } finally {
          setBusy(false);
        }
      }}
    />
  );

  return { pick, busy, note, setNote, dialog };
}

/** Картинка → файл нужной формы. Логотип — PNG: поля вокруг остаются
 *  прозрачными и на плитке сливаются с цветом витрины. */
async function render(
  image: HTMLImageElement,
  frame: Frame,
  view: View,
  shape: ImageShape,
  sourceType: string,
): Promise<Blob> {
  // Мельче, чем видно в рамке из исходника, не растягиваем: крупнее не станет.
  const visible = frame.width / view.scale;
  const width = Math.round(Math.min(OUTPUT[shape], Math.max(visible, 64)));
  const height = Math.round(width / RATIO[shape]);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("телефон не дал нарисовать картинку");
  const png = shape === "logo" || /png|webp|gif/.test(sourceType);
  if (!png) {
    context.fillStyle = "#fff";
    context.fillRect(0, 0, width, height);
  }
  context.imageSmoothingQuality = "high";
  const k = width / frame.width;
  context.drawImage(
    image,
    view.x * k,
    view.y * k,
    image.naturalWidth * view.scale * k,
    image.naturalHeight * view.scale * k,
  );
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("картинка не сохранилась"))),
      png ? "image/png" : "image/jpeg",
      0.86,
    ),
  );
}

export function ImageCrop({
  file,
  shape,
  busy,
  onCancel,
  onSave,
}: {
  file: File | null;
  shape: ImageShape;
  busy: boolean;
  onCancel: () => void;
  /** Бросает ошибку — окно остаётся открытым с причиной */
  onSave: (image: Blob) => Promise<void>;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [natural, setNatural] = useState<Frame | null>(null);
  const [view, setView] = useState<View | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const picture = useRef<HTMLImageElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  const latest = useRef({ frame, natural, view });
  latest.current = { frame, natural, view };

  useEffect(() => {
    setError(null);
    setBroken(false);
    setNatural(null);
    setView(null);
    if (!file) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  // Пока окно открыто, страница под ним не прокручивается, а свайп вниз не
  // сворачивает приложение.
  useEffect(() => {
    if (!file) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const release = holdVerticalSwipes();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && cancel.current();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      release();
      window.removeEventListener("keydown", onKey);
    };
  }, [file]);

  // Размер рамки — по её месту на экране: поворот телефона меняет его.
  useEffect(() => {
    const node = box.current;
    if (!node || !url) return;
    const measure = () => setFrame({ width: node.clientWidth, height: node.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [url]);

  /** Меньше этого снимок не уменьшается: фото заполняет рамку целиком,
   *  а логотип можно уменьшить, пока он весь не поместится. */
  const minScale = useCallback(
    (f: Frame, n: Frame) =>
      shape === "logo"
        ? Math.min(f.width / n.width, f.height / n.height)
        : Math.max(f.width / n.width, f.height / n.height),
    [shape],
  );

  /** Снимок не отъезжает от края рамки: пустых полос у фото не бывает.
   *  У логотипа меньше рамки — он просто остаётся в её пределах. */
  const clamp = useCallback(
    (next: View, f: Frame, n: Frame): View => {
      const low = minScale(f, n);
      const scale = Math.min(Math.max(next.scale, low), low * ZOOM);
      const w = n.width * scale;
      const h = n.height * scale;
      const fit = (pos: number, size: number, room: number) =>
        size >= room ? Math.min(0, Math.max(room - size, pos)) : Math.min(room - size, Math.max(0, pos));
      return { scale, x: fit(next.x, w, f.width), y: fit(next.y, h, f.height) };
    },
    [minScale],
  );

  // Первый вид — снимок по центру, как можно крупнее целиком в рамке
  // (у логотипа — целиком виден).
  useEffect(() => {
    if (!frame || !natural || view) return;
    const scale = shape === "logo"
      ? minScale(frame, natural)
      : Math.max(frame.width / natural.width, frame.height / natural.height);
    setView(
      clamp(
        {
          scale,
          x: (frame.width - natural.width * scale) / 2,
          y: (frame.height - natural.height * scale) / 2,
        },
        frame,
        natural,
      ),
    );
  }, [frame, natural, view, shape, minScale, clamp]);

  // Рамка поменяла размер — вид пересчитывается заново.
  useEffect(() => setView(null), [frame?.width, frame?.height]);

  const zoomAt = useCallback(
    (factor: number, px: number, py: number) => {
      const { frame: f, natural: n, view: v } = latest.current;
      if (!f || !n || !v) return;
      const scale = v.scale * factor;
      setView(
        clamp(
          { scale, x: px - (px - v.x) * (scale / v.scale), y: py - (py - v.y) * (scale / v.scale) },
          f,
          n,
        ),
      );
    },
    [clamp],
  );

  // Колесо мыши — масштаб у курсора. Не пассивный: иначе прокрутится страница.
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = node.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [url, zoomAt]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const points = pointers.current;
    const before = points.get(event.pointerId);
    if (!before) return;
    const { frame: f, natural: n, view: v } = latest.current;
    if (!f || !n || !v) return;
    const others = [...points.entries()].filter(([id]) => id !== event.pointerId);
    points.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (!others.length) {
      // Один палец — двигаем снимок.
      setView(clamp({ ...v, x: v.x + event.clientX - before.x, y: v.y + event.clientY - before.y }, f, n));
      return;
    }
    // Два пальца — масштаб вокруг точки между ними.
    const [, other] = others[0];
    const was = Math.hypot(before.x - other.x, before.y - other.y);
    const now = Math.hypot(event.clientX - other.x, event.clientY - other.y);
    if (was < 1) return;
    const rect = event.currentTarget.getBoundingClientRect();
    zoomAt(now / was, (event.clientX + other.x) / 2 - rect.left, (event.clientY + other.y) / 2 - rect.top);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId);
  };

  if (!file || !url) return null;

  const low = frame && natural ? minScale(frame, natural) : 1;
  // Ползунок — в долях от «наименьшего» до «вчетверо крупнее».
  const level = view ? Math.log(view.scale / low) / Math.log(ZOOM) : 0;

  async function save() {
    const image = picture.current;
    if (!image || !frame || !view) return;
    setError(null);
    try {
      await onSave(await render(image, frame, view, shape, file!.type));
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    }
  }

  async function saveAsIs() {
    setError(null);
    try {
      await onSave(file!);
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    }
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Кадрирование картинки"
      className="anim-fade fixed inset-0 z-50 flex flex-col bg-black/92 px-4
                 pt-[max(16px,env(safe-area-inset-top))] pb-[max(16px,env(safe-area-inset-bottom))]"
    >
      <div className="mx-auto flex w-full max-w-[520px] flex-1 flex-col justify-center gap-4">
        <div>
          <p className="t-title text-white">Что будет видно</p>
          <p className="t-desc mt-1 text-white/70">
            {broken
              ? "Этот формат телефон не показывает — можно загрузить снимок как есть."
              : "Двигайте снимок пальцем, увеличивайте двумя пальцами или ползунком."}
          </p>
        </div>

        {!broken && (
          <div
            ref={box}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            className={`relative w-full touch-none overflow-hidden rounded-2xl select-none ${
              shape === "logo" ? "bg-[repeating-conic-gradient(#3a3a3a_0_25%,#2a2a2a_0_50%)] bg-[length:16px_16px]" : "bg-white/10"
            }`}
            style={{
              aspectRatio: String(RATIO[shape]),
              // Квадрат не выше половины экрана: кнопки остаются на виду.
              maxWidth: shape === "cover" ? undefined : "min(100%, 52dvh)",
              marginInline: "auto",
            }}
          >
            <img
              ref={picture}
              src={url}
              alt=""
              draggable={false}
              onLoad={(event) =>
                setNatural({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                })
              }
              onError={() => setBroken(true)}
              className="pointer-events-none absolute top-0 left-0 max-w-none origin-top-left"
              style={
                view && natural
                  ? {
                      width: natural.width * view.scale,
                      height: natural.height * view.scale,
                      transform: `translate3d(${view.x}px, ${view.y}px, 0)`,
                    }
                  : { opacity: 0 }
              }
            />
            <div className="pointer-events-none absolute inset-0 rounded-2xl ring-1 ring-white/40 ring-inset" />
          </div>
        )}

        {!broken && (
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={Math.min(1, Math.max(0, level))}
            aria-label="Масштаб"
            onChange={(event) => {
              const { frame: f, view: v } = latest.current;
              if (!f || !v) return;
              const target = low * ZOOM ** Number(event.target.value);
              zoomAt(target / v.scale, f.width / 2, f.height / 2);
            }}
            className="w-full accent-[var(--accent)]"
          />
        )}

        {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onCancel}
            className={`${chipClass("neutral")} h-[52px] w-[120px] text-[15px]/[20px]`}
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={busy || (!broken && !view)}
            onClick={() => void (broken ? saveAsIs() : save())}
            className="h-[52px] flex-1 rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-60"
          >
            {busy ? "Сохраняю…" : broken ? "Загрузить как есть" : "Сохранить"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
