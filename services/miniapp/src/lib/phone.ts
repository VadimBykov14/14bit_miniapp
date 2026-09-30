/** Телефон по маске «+7 (900) 123-45-67».
 *
 *  Номер российский и ровно из 11 цифр: восьмёрка в начале становится
 *  семёркой. Сервер проверяет то же самое, а маска просто не даёт набрать
 *  лишнего — иначе человек узнаёт о лишней цифре только отказом.
 */

/** Что набрано или вставлено → номер по маске, сколько цифр уже есть. */
export function formatPhone(input: string): string {
  const digits = input.replace(/\D/g, "");
  if (!digits) return "";
  // Номер без кода страны («900…») — тоже российский: код подставляем.
  const rest = (/^[78]/.test(digits) ? digits.slice(1) : digits).slice(0, 10);
  if (!rest) return "+7";
  let out = `+7 (${rest.slice(0, 3)}`;
  if (rest.length > 3) out += `) ${rest.slice(3, 6)}`;
  if (rest.length > 6) out += `-${rest.slice(6, 8)}`;
  if (rest.length > 8) out += `-${rest.slice(8, 10)}`;
  return out;
}

/** Номер набран целиком или не набран вовсе — такой можно сохранять. */
export const phoneReady = (value: string): boolean => {
  const digits = value.replace(/\D/g, "").length;
  return digits === 0 || digits === 11;
};
