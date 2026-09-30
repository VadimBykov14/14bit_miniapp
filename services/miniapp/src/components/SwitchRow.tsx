/** Переключатель настройки справа от подписи — как в настройках MAX.
 *
 *  На компоненте кита: Switch из HeroUI рисуется нашими токенами и
 *  приносит клавиатуру и озвучку из React Aria. Нажимается вся строка,
 *  а не только сам бегунок.
 */

import { Label, Switch } from "@heroui/react";

export function SwitchRow({
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
    <Switch
      isSelected={checked}
      isDisabled={disabled}
      onChange={onChange}
      className="switch-row w-full"
    >
      <Switch.Content className="flex w-full items-center gap-3 text-left">
        <span className="min-w-0 flex-1">
          <Label className="t-detail block">{label}</Label>
          {hint && <span className="t-label mt-[2px] block text-text-secondary">{hint}</span>}
        </span>
        <Switch.Control className="shrink-0">
          <Switch.Thumb />
        </Switch.Control>
      </Switch.Content>
    </Switch>
  );
}
