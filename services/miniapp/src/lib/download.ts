/** Скачивание файла из мини-приложения.
 *
 *  Внутри MAX файл качает сам мессенджер: вебвью blob-ссылки не сохраняет,
 *  и кнопка «В Excel» молча ничего не делала. MAX получает только адрес,
 *  поэтому сервер выдаёт на выгрузку короткоживущую подписанную ссылку.
 *
 *  В обычном браузере — по-старому: заголовок с подписью, fetch и
 *  blob-ссылка, потому что <a href> заголовков не передаёт.
 */

import { failure, getDownloadLink } from "./api";
import { downloadInMax, isInsideMax, rawInitData } from "./bridge";

export async function fetchFile(path: string, activeRole: string | null): Promise<void> {
  if (isInsideMax()) {
    const link = await getDownloadLink(`/api${path}`);
    if (downloadInMax(`${window.location.origin}${link.url}`, link.file_name)) return;
  }

  const headers = new Headers();
  headers.set("X-Max-Init-Data", rawInitData() || "");
  if (activeRole) headers.set("X-Active-Role", activeRole);

  const response = await fetch(`/api${path}`, { headers });
  if (!response.ok) throw await failure(response);

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const name = match?.[1] ?? "file.csv";
  const url = URL.createObjectURL(await response.blob());

  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    // Отзываем не сразу: некоторые вебвью начинают скачивание асинхронно
    // и по отозванной ссылке получают пустой файл.
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}
