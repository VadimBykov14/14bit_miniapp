/** «Написать» человеку в MAX.
 *
 *  Если у человека есть публичный ник — открываем его профиль сразу.
 *  Если нет, прямую ссылку не построить: адрес max.ru/u/… выдаёт сам
 *  мессенджер, из номера пользователя он не вычисляется. Тогда бот
 *  присылает в чат с ним карточку контакта, а мы открываем этот чат —
 *  нажатие на карточку ведёт в профиль с кнопкой «Написать».
 */

import { reach } from "./api";
import { haptic, isInsideMax, openMaxLink } from "./bridge";

export type WriteTarget = { employee_id?: number; client_id?: number; worker_id?: number };

export async function writeTo(
  target: WriteTarget,
  direct: string,
  notify: (text: string) => void,
): Promise<void> {
  if (direct) {
    openMaxLink(direct);
    return;
  }
  try {
    const result = await reach(target);
    if (result.chat_href) {
      openMaxLink(result.chat_href);
      return;
    }
    if (!result.sent) {
      haptic("error");
      notify("Не получилось прислать контакт. Попробуйте позвонить.");
      return;
    }
    haptic("success");
    notify("Контакт в чате с ботом — нажмите на карточку, чтобы написать.");
    if (result.bot_href && isInsideMax()) openMaxLink(result.bot_href);
  } catch (err) {
    haptic("error");
    notify((err as Error).message);
  }
}
