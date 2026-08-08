'use client';

import { Button } from '@heroui/react';
import { Search, Filter, RefreshCcw, Inbox } from 'lucide-react';

type Variant = 'no-results' | 'no-data' | 'error';

type Props = {
  variant?: Variant;
  /** main headline */
  title?: string;
  /** helper text below the headline */
  description?: string;
  /** what filters/search are active — to give a useful hint */
  hasFilters?: boolean;
  hasSearch?: boolean;
  onResetFilters?: () => void;
  onResetSearch?: () => void;
  onRefresh?: () => void;
  errorMessage?: string;
};

/**
 * Empty-state illustration. Three variants:
 *
 *   - 'no-results' — filters or search returned nothing
 *   - 'no-data'    — the table is empty (no rows at all)
 *   - 'error'      — fetch failed
 *
 * Always previews the next action: clear filters, clear search, or
 * refresh. So the user never gets stuck on a blank table.
 */
export default function EmptyState({
  variant = 'no-results',
  title,
  description,
  hasFilters = false,
  hasSearch = false,
  onResetFilters,
  onResetSearch,
  onRefresh,
  errorMessage,
}: Props) {
  let Icon = Inbox;
  let defaultTitle = 'Ничего не нашлось';
  let defaultDesc = 'Попробуй изменить фильтры или поисковый запрос';

  if (variant === 'no-data') {
    Icon = Inbox;
    defaultTitle = 'Пока пусто';
    defaultDesc = 'Когда появятся объявления, они отобразятся здесь';
  } else if (variant === 'error') {
    Icon = Inbox;
    defaultTitle = 'Не удалось загрузить';
    defaultDesc = errorMessage || 'Проверь подключение к API и попробуй ещё раз';
  } else if (hasSearch && hasFilters) {
    Icon = Filter;
    defaultTitle = 'По этому набору фильтров ничего не нашлось';
    defaultDesc = 'Попробуй ослабить фильтры или сбросить поиск';
  } else if (hasSearch) {
    Icon = Search;
    defaultTitle = 'Поиск не дал результатов';
    defaultDesc = 'Проверь опечатки или попробуй другие ключевые слова';
  } else if (hasFilters) {
    Icon = Filter;
    defaultTitle = 'Фильтры слишком строгие';
    defaultDesc = 'Сбрось фильтры или расширь диапазоны';
  }

  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="w-14 h-14 rounded-2xl bg-default-100 text-default-400 flex items-center justify-center mb-4">
        <Icon size={28} strokeWidth={1.5} />
      </div>
      <div className="text-[15px] font-semibold text-default-900">{title || defaultTitle}</div>
      <div className="text-[13px] text-default-500 mt-1.5 max-w-[400px] leading-relaxed">
        {description || defaultDesc}
      </div>

      {(hasFilters || hasSearch || onRefresh) && (
        <div className="mt-5 flex items-center gap-2">
          {hasFilters && onResetFilters && (
            <Button
              size="sm"
              variant="flat"
              onPress={onResetFilters}
              className="bg-default-100 data-[hover=true]:bg-default-200 text-default-700"
            >
              Сбросить фильтры
            </Button>
          )}
          {hasSearch && onResetSearch && (
            <Button
              size="sm"
              variant="flat"
              onPress={onResetSearch}
              className="bg-default-100 data-[hover=true]:bg-default-200 text-default-700"
            >
              Очистить поиск
            </Button>
          )}
          {onRefresh && (
            <Button
              size="sm"
              variant="bordered"
              onPress={onRefresh}
              startContent={<RefreshCcw size={12} />}
              className="border-default-200 data-[hover=true]:bg-default-100"
            >
              Обновить
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
