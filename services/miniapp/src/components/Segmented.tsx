/** Переключатель «В работе / История» — на Tabs из HeroUI.
 *
 *  Подсветка выбранного переезжает к нажатому плавно, а выбор живёт в
 *  адресе: вернувшись из заявки, человек снова видит историю, а не
 *  начинает с первой вкладки.
 */

import { Tabs } from "@heroui/react";

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <Tabs
      selectedKey={value}
      onSelectionChange={(key) => onChange(String(key) as T)}
      className="segmented"
    >
      <Tabs.ListContainer>
        <Tabs.List aria-label={label}>
          {options.map((option) => (
            <Tabs.Tab key={option.value} id={option.value} className="segmented__tab">
              {option.label}
              {Boolean(option.count) && (
                <span className="segmented__count">{option.count}</span>
              )}
              <Tabs.Indicator className="segmented__indicator" />
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs.ListContainer>
    </Tabs>
  );
}
