/** Переключатель настройки — на компоненте кита.
 *
 *  Сырой <input type="checkbox"> в вебвью выглядит по-разному на iOS и
 *  Android и не попадает в тему MAX. Checkbox из HeroUI рисуется нашими
 *  токенами и приносит клавиатуру и озвучку из React Aria.
 */

import { Checkbox, Label } from "@heroui/react";

export function Toggle({
  label,
  hint,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <Checkbox isSelected={checked} isDisabled={disabled} onChange={onChange}>
      <Checkbox.Content className="flex w-full items-start gap-3">
        {/* 20 px вместо 16: палец промахивается мимо мелкого квадрата,
            хотя нажимается и вся строка. */}
        <Checkbox.Control className="mt-0 size-5 shrink-0 rounded-[6px]">
          <Checkbox.Indicator />
        </Checkbox.Control>
        <span className="min-w-0 flex-1">
          <Label className="t-detail block">{label}</Label>
          {hint && <span className="t-label block text-text-secondary">{hint}</span>}
        </span>
      </Checkbox.Content>
    </Checkbox>
  );
}
