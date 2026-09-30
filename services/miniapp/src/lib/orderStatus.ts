/** Где подпись статуса зависит не только от самого статуса.
 *
 *  «В сборке» у витрины «под заказ» — это производство: пекарня после
 *  отсечки печёт, а не собирает со склада. Отказ поставщика после
 *  подтверждения — отменённая поставка: о заявке уже договорились, и
 *  «Отклонена» читалась бы как «её даже не рассматривали».
 *
 *  Остальные подписи у каждого экрана свои — например, клиенту «Отгружена ·
 *  примите», — поэтому здесь только эти два случая.
 */

import type { Order } from "./api";

export function specialLabel(
  order: Pick<Order, "status" | "storefront_mode" | "confirmed_at">,
): string | null {
  if (order.status === "assembling" && order.storefront_mode === "preorder") {
    return "В производстве";
  }
  if (order.status === "rejected" && order.confirmed_at) return "Отменена поставщиком";
  return null;
}
