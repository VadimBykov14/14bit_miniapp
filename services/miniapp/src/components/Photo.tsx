/** Снимок, который проявляется, когда загрузился.
 *
 *  Без этого фото товара рисовалось построчно поверх пустого места, и
 *  каталог «мигал» при каждом открытии. Из кэша браузера снимок приходит
 *  сразу — тогда и проявления нет.
 */

import { useState } from "react";

export function Photo({
  src,
  alt = "",
  className = "",
  lazy = true,
}: {
  src: string;
  alt?: string;
  className?: string;
  lazy?: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  return (
    <img
      src={src}
      alt={alt}
      loading={lazy ? "lazy" : undefined}
      decoding="async"
      data-loaded={loaded}
      ref={(node) => {
        // Уже в кэше: onLoad мог сработать до того, как React повесил
        // обработчик, и снимок остался бы прозрачным.
        if (node?.complete && node.naturalWidth > 0 && !loaded) setLoaded(true);
      }}
      onLoad={() => setLoaded(true)}
      onError={() => setLoaded(true)}
      className={`photo ${className}`}
    />
  );
}
