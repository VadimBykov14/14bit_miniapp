/** Иконки 20×20 по сетке макета. Отдельная библиотека ради шести штук не нужна. */

type Props = { className?: string };

const base = { width: 20, height: 20, viewBox: "0 0 20 20", fill: "none" } as const;

export const ChevronRight = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <path
      d="M7.5 4.5L13 10l-5.5 5.5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Repeat = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <path
      d="M16.5 10a6.5 6.5 0 1 1-1.9-4.6"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
    <path
      d="M16.5 3.2v3.1h-3.1"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Clock = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <circle cx="10" cy="10" r="6.9" stroke="currentColor" strokeWidth="1.5" />
    <path
      d="M10 6.2V10l2.6 1.8"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const tab = { width: 24, height: 24, viewBox: "0 0 24 24", fill: "none" } as const;

export const HomeIcon = ({ className }: Props) => (
  <svg {...tab} className={className} aria-hidden="true">
    <path
      d="M4 10.2 12 4l8 6.2V19a1 1 0 0 1-1 1h-4v-5H9v5H5a1 1 0 0 1-1-1v-8.8Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

export const ShopIcon = ({ className }: Props) => (
  <svg {...tab} className={className} aria-hidden="true">
    <path
      d="M4 9h16l-1 10.2a1 1 0 0 1-1 .8H6a1 1 0 0 1-1-.8L4 9Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path d="M8.5 9V7a3.5 3.5 0 1 1 7 0v2" stroke="currentColor" strokeWidth="1.6" />
  </svg>
);

export const ListIcon = ({ className }: Props) => (
  <svg {...tab} className={className} aria-hidden="true">
    <rect x="4.2" y="4.2" width="15.6" height="15.6" rx="3" stroke="currentColor" strokeWidth="1.6" />
    <path
      d="M8 9h8M8 12.5h8M8 16h5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  </svg>
);

export const PersonIcon = ({ className }: Props) => (
  <svg {...tab} className={className} aria-hidden="true">
    <circle cx="12" cy="8.4" r="3.6" stroke="currentColor" strokeWidth="1.6" />
    <path
      d="M4.8 20c.6-3.6 3.6-5.6 7.2-5.6s6.6 2 7.2 5.6"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  </svg>
);

/* Мелкие значки 16×16 для кнопок-пилюль. */
const chip = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none" } as const;

export const CalendarIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <rect x="2.2" y="3.2" width="11.6" height="10.6" rx="2" stroke="currentColor" strokeWidth="1.4" />
    <path d="M2.5 6.6h11M5.4 1.8v2.6M10.6 1.8v2.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const DownloadIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <path d="M8 2.2v7.6M4.8 6.8 8 10l3.2-3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M2.6 12.2v.6a1.2 1.2 0 0 0 1.2 1.2h8.4a1.2 1.2 0 0 0 1.2-1.2v-.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const PhoneIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <path
      d="M5.6 2.4 4 2.2a1.4 1.4 0 0 0-1.5 1.2c-.3 2.4.6 5 2.7 7.1s4.7 3 7.1 2.7a1.4 1.4 0 0 0 1.2-1.5l-.2-1.6a1 1 0 0 0-.8-.9l-1.8-.4a1 1 0 0 0-1 .3l-.7.8a7.4 7.4 0 0 1-3-3l.8-.7a1 1 0 0 0 .3-1l-.4-1.8a1 1 0 0 0-.9-.8Z"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinejoin="round"
    />
  </svg>
);

export const ChatIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <path
      d="M3.2 12.6 2.4 14l2.3-.9A6 6 0 1 0 2 8a5.9 5.9 0 0 0 1.2 3.6"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const CheckIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <path d="m3.2 8.4 3 3 6.6-6.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const ShieldIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <path
      d="M8 1.9 3 3.8v3.9c0 3 2.1 5.6 5 6.4 2.9-.8 5-3.4 5-6.4V3.8L8 1.9Z"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinejoin="round"
    />
    <path d="m5.8 8 1.5 1.5 2.9-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const LockIcon = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <rect x="4" y="8.6" width="12" height="8.4" rx="2" stroke="currentColor" strokeWidth="1.6" />
    <path d="M6.8 8.6V6.4a3.2 3.2 0 0 1 6.4 0v2.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

export const SearchIcon = ({ className }: Props) => (
  <svg {...chip} className={className} aria-hidden="true">
    <circle cx="7.2" cy="7.2" r="4.6" stroke="currentColor" strokeWidth="1.5" />
    <path d="m10.6 10.6 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const TrashIcon = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <path
      d="M4 5.5h12M8 5.5V4h4v1.5M5.5 5.5l.7 10.1c.05.8.7 1.4 1.5 1.4h4.6c.8 0 1.45-.6 1.5-1.4l.7-10.1"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const CloseIcon = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

export const BookmarkIcon = ({ className }: Props) => (
  <svg {...base} className={className} aria-hidden="true">
    <path
      d="M5.5 3.5h9a1 1 0 0 1 1 1v12.2l-5.5-3.6-5.5 3.6V4.5a1 1 0 0 1 1-1Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

/** Звёздочка избранного: контур — не отмечено, залита — в избранном. */
export const StarIcon = ({ className, filled = false }: Props & { filled?: boolean }) => (
  <svg {...base} className={className} aria-hidden="true">
    <path
      d="M10 2.9l2.1 4.3 4.7.7-3.4 3.3.8 4.7L10 13.7l-4.2 2.2.8-4.7-3.4-3.3 4.7-.7L10 2.9Z"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinejoin="round"
      fill={filled ? "currentColor" : "none"}
    />
  </svg>
);
