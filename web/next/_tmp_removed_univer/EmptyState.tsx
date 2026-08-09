'use client';

import { Button } from '@heroui/react';
import { Search, Filter, Inbox, AlertCircle, RefreshCcw } from 'lucide-react';

type Variant = 'no-results' | 'no-data' | 'error';

type Props = {
  variant?: Variant;
  title?: string;
  description?: string;
  hasFilters?: boolean;
  hasSearch?: boolean;
  onResetFilters?: () => void;
  onResetSearch?: () => void;
  onRefresh?: () => void;
  errorMessage?: string;
};

/**
 * Empty-state placeholder. Three variants:
 *   - no-data:   the table is empty (no filters, no search)
 *   - no-results: filters/search returned nothing
 *   - error:     API call failed
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
    defaultTitle = 'Реестр пуст';
    defaultDesc = 'Когда появятся записи, они отобразятся здесь';
  } else if (variant === 'error') {
    Icon = AlertCircle;
    defaultTitle = 'Не удалось получить данные';
    defaultDesc = errorMessage || 'Проверь подключение к API и попробуй ещё раз';
  } else if (hasSearch && hasFilters) {
    Icon = Filter;
    defaultTitle = 'По этому набору ничего не нашлось';
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
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center bg-[var(--paper-card)]">
      <div className="w-12 h-12 rounded-full bg-[var(--paper-2)] flex items-center justify-center mb-4 text-[var(--ink-mute)]">
        <Icon size={22} strokeWidth={1.5} />
      </div>
      <div className="text-[15px] font-semibold text-[var(--ink)]">
        {title || defaultTitle}
      </div>
      <div className="text-[13px] text-[var(--ink-mute)] mt-1.5 max-w-[420px] leading-relaxed">
        {description || defaultDesc}
      </div>

      {(hasFilters || hasSearch || (onRefresh && variant === 'error')) && (
        <div className="mt-5 flex items-center gap-2 flex-wrap justify-center">
          {hasFilters && onResetFilters && (
            <Button size="md" variant="bordered" onPress={onResetFilters}>
              Сбросить фильтры
            </Button>
          )}
          {hasSearch && onResetSearch && (
            <Button size="md" variant="bordered" onPress={onResetSearch}>
              Очистить поиск
            </Button>
          )}
          {onRefresh && variant === 'error' && (
            <Button
              size="md"
              color="primary"
              startContent={<RefreshCcw size={13} strokeWidth={2} />}
              onPress={onRefresh}
            >
              Повторить
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
