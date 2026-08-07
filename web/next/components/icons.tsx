// Single place for inline SVG icons used across the app.
// `currentColor` lets the parent control colour via `text-*` Tailwind
// classes; `strokeWidth` is 1.6 by default (HeroUI-ish) for outline icons
// and unset for solid glyphs.
//
// Sizes are passed via the standard `width`/`height` props (defaults to 16).

import type { SVGProps } from 'react';

type Props = SVGProps<SVGSVGElement> & { size?: number };

function withDefaults({ size = 16, strokeWidth = 1.6, ...rest }: Props): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    ...rest,
  };
}

/** Метро — стиль 2gis: буква M в круглом значке.
 *  Иконка взята из CIAN-style глифа, рисуется сплошным контуром. */
export function MetroIcon(props: Props) {
  const { size = 16, ...rest } = props;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="currentColor"
      {...rest}
    >
      <path d="M13 11h-3v-1h.4l-.9-2.4L8 10.1 6.4 7.7 5.6 10H6v1H3v-1h.6l2.5-6.2L8 6.7l1.9-2.9 2.5 6.2h.6v1z" />
    </svg>
  );
}

/** Пешеход — для «N мин пешком».
 *  Иконка из Я.Недвижимости (залитый глиф, без обводки). */
export function WalkIcon(props: Props) {
  const { size = 16, ...rest } = props;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
      {...rest}
    >
      <g fill="currentColor">
        <path d="M8.867 4.475c.966 0 1.75-.779 1.75-1.74 0-.96-.784-1.738-1.75-1.738-.967 0-1.75.778-1.75 1.739A1.74 1.74 0 0 0 8.34 4.394l-4.4 1.289-1.137 2.97 1.867.715.784-2.044 1.12-.329-2.929 8.008h2.13l.094-.259-.016-.006 2.556-6.937.258-.707 1.192.91h3.338v-2h-2.662L8.473 4.43q.19.045.394.045" />
        <path d="M11.197 15.003h-2v-3.586l-.77-.77.761-2.067 2.01 2.009z" />
      </g>
    </svg>
  );
}

/** Здание (год постройки). */
export function BuildingIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <path d="M2.5 13.5V3.6l5-1.4v11.3" />
      <path d="M7.5 13.5V6.5l6 1.6v5.4" />
      <path d="M1.5 13.5h13" />
      <path d="M4.2 5.2h1.4M4.2 7.6h1.4M4.2 10h1.4" />
      <path d="M9.4 8.6h1.4M9.4 10.7h1.4" />
    </svg>
  );
}

/** Этажи (для «N эт.»). */
export function FloorsIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1" />
      <path d="M2.5 6h11M2.5 9.5h11M5 6v3.5M8 6v3.5M11 6v3.5" />
    </svg>
  );
}

/** Планировка (для isCianLayout фоток). */
export function PlanIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <rect x="2" y="2.5" width="12" height="11" rx="1" />
      <path d="M5.5 2.5v11M10.5 6.5h3.5M2 6.5h3.5" />
      <circle cx="12" cy="4.5" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Календарь (для дней на сайте / даты). */
export function CalendarIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <rect x="2" y="3" width="12" height="11" rx="1.5" />
      <path d="M2 6.2h12" />
      <path d="M5 1.5v3M11 1.5v3" />
    </svg>
  );
}

/** Внешняя ссылка (для ЦИАН). */
export function ExternalIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <path d="M9 2.5h4.5V7" />
      <path d="M13.5 2.5L7 9" />
      <path d="M12.5 9.2v3.3a1 1 0 01-1 1H3.5a1 1 0 01-1-1V4.5a1 1 0 011-1h3.3" />
    </svg>
  );
}

/** Стрелка влево — для кнопок карусели (custom под 2gis). */
export function ChevronLeftIcon(props: Props) {
  const { size = 14, strokeWidth = 2.5, ...rest } = props;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

export function ChevronRightIcon(props: Props) {
  const { size = 14, strokeWidth = 2.5, ...rest } = props;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

/** Камера — для бейджа «N фото». */
export function CameraIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <path d="M2.5 5.5a1 1 0 011-1h2.2l1.1-1.5h2.4l1.1 1.5h2.2a1 1 0 011 1v6.5a1 1 0 01-1 1h-9a1 1 0 01-1-1V5.5z" />
      <circle cx="8" cy="9" r="2" />
    </svg>
  );
}

/** Fullscreen — кнопка «открыть на весь экран». */
export function FullscreenIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <path d="M3 6V3h3" />
      <path d="M13 3h3v3" />
      <path d="M16 13v3h-3" />
      <path d="M3 10v3h3" />
    </svg>
  );
}

/** Крестик — для close-иконки, если понадобится (HeroUI даёт свой). */
export function CloseIcon(props: Props) {
  return (
    <svg {...withDefaults(props)}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}
