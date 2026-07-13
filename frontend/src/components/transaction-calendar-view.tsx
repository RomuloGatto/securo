import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeftRight, CalendarDays, CircleDot } from 'lucide-react'
import type { TransactionCalendarDay, TransactionCalendarItem, TransactionCalendarResponse } from '@/types'
import { Skeleton } from '@/components/ui/skeleton'
import { CategoryIcon } from '@/components/category-icon'
import { cn } from '@/lib/utils'

function parseLocalDate(value: string) {
  return new Date(`${value}T00:00:00`)
}

function formatCurrency(value: number, currency = 'USD', locale = 'en-US') {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value)
}

function compactCurrency(value: number, currency = 'USD', locale = 'en-US') {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

function signedAmount(item: TransactionCalendarItem) {
  return item.type === 'credit' ? Math.abs(item.amount) : -Math.abs(item.amount)
}

function displayDayNumber(date: string) {
  return parseLocalDate(date).getDate()
}

function todayIso() {
  return new Date().toISOString().split('T')[0]
}

type CalendarMarkerTone = 'income' | 'expense' | 'transfer' | 'projected'
type CalendarDensity = 'compact' | 'detailed'
const CALENDAR_DENSITY_STORAGE_KEY = 'securo.transactionCalendar.density'

function readCalendarDensity(): CalendarDensity {
  if (typeof window === 'undefined') return 'compact'
  return window.localStorage.getItem(CALENDAR_DENSITY_STORAGE_KEY) === 'detailed' ? 'detailed' : 'compact'
}

export function TransactionCalendarView({
  calendar,
  isLoading,
  locale,
  dateLocale,
  mask,
  selectedDate,
  onSelectedDateChange,
  onOpenTransaction,
}: {
  calendar?: TransactionCalendarResponse
  isLoading: boolean
  locale: string
  dateLocale: string
  mask: (value: string) => string
  selectedDate: string
  onSelectedDateChange: (date: string) => void
  onOpenTransaction: (id: string) => void
}) {
  const [density, setDensity] = useState<CalendarDensity>(readCalendarDensity)

  useEffect(() => {
    window.localStorage.setItem(CALENDAR_DENSITY_STORAGE_KEY, density)
  }, [density])

  useEffect(() => {
    if (!calendar?.days.length) return
    if (selectedDate && calendar.days.some((day) => day.date === selectedDate)) return
    const today = todayIso()
    const inCalendarToday = calendar.days.find((day) => day.date === today)
    const firstInMonth = calendar.days.find((day) => day.in_month)
    onSelectedDateChange((inCalendarToday ?? firstInMonth ?? calendar.days[0]).date)
  }, [calendar, onSelectedDateChange, selectedDate])

  const selectedDay = calendar?.days.find((day) => day.date === selectedDate)
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, index) => {
      const date = new Date(Date.UTC(2024, 0, 7 + index)) // Sunday-start reference week
      return date.toLocaleDateString(dateLocale, { weekday: 'short' })
    }),
    [dateLocale],
  )

  if (isLoading) {
    return (
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden mb-4">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <Skeleton className="h-6 w-44" />
          <Skeleton className="h-8 w-32" />
        </div>
        <div className="grid grid-cols-7">
          {Array.from({ length: 35 }).map((_, index) => (
            <div key={index} className="min-h-32 border-r border-b border-border p-3">
              <Skeleton className="h-4 w-8 mb-4" />
              <Skeleton className="h-4 w-24" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!calendar) return null

  return (
    <div className="mb-4 flex flex-col gap-4 md:flex-row md:items-start">
      <section className="min-w-0 flex-1 bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border sm:px-5">
          <CalendarLegend />
          <CalendarDensityToggle value={density} onChange={setDensity} />
        </div>

        <div className="hidden md:grid grid-cols-7 border-b border-border bg-muted/30">
          {weekDays.map((day) => (
            <div key={day} className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {day}
            </div>
          ))}
        </div>

        <div className="hidden md:grid grid-cols-7">
          {calendar.days.map((day) => (
            <DayCell
              key={day.date}
              day={day}
              selected={day.date === selectedDate}
              today={day.date === todayIso()}
              currency={calendar.currency}
              locale={locale}
              mask={mask}
              density={density}
              onSelect={() => onSelectedDateChange(day.date)}
            />
          ))}
        </div>

        <div className="md:hidden divide-y divide-border">
          {calendar.days.filter((day) => day.in_month).map((day) => (
            <MobileDayRow
              key={day.date}
              day={day}
              selected={day.date === selectedDate}
              currency={calendar.currency}
              locale={locale}
              dateLocale={dateLocale}
              mask={mask}
              density={density}
              onSelect={() => onSelectedDateChange(day.date)}
            />
          ))}
        </div>
      </section>

      <SelectedDayPanel
        day={selectedDay}
        currency={calendar.currency}
        locale={locale}
        dateLocale={dateLocale}
        mask={mask}
        onOpenTransaction={onOpenTransaction}
      />
    </div>
  )
}

function CalendarLegend() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <span className="font-semibold uppercase tracking-wide">{t('transactions.calendarLegend')}</span>
      <LegendItem tone="income" label={t('transactions.summaryIncome')} />
      <LegendItem tone="expense" label={t('transactions.summaryExpenses')} />
      <LegendItem tone="transfer" label={t('transactions.transfer')}>
        <ArrowLeftRight size={9} />
      </LegendItem>
      <LegendItem tone="projected" label={t('transactions.calendarProjected')}>
        <CalendarDays size={9} />
      </LegendItem>
    </div>
  )
}

function CalendarDensityToggle({ value, onChange }: { value: CalendarDensity; onChange: (value: CalendarDensity) => void }) {
  const { t } = useTranslation()
  const options: Array<{ value: CalendarDensity; label: string }> = [
    { value: 'compact', label: t('transactions.calendarCompact') },
    { value: 'detailed', label: t('transactions.calendarDetailed') },
  ]
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted/30 p-0.5 text-xs" aria-label={t('transactions.calendarDensity')}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            'rounded-md px-2.5 py-1 font-semibold text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40',
            value === option.value && 'bg-card text-foreground shadow-sm dark:bg-background',
          )}
          aria-pressed={value === option.value}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function LegendItem({ tone, label, children }: { tone: CalendarMarkerTone; label: string; children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <BadgeDot tone={tone} label={label}>{children}</BadgeDot>
      <span>{label}</span>
    </span>
  )
}

function DayCell({
  day,
  selected,
  today,
  currency,
  locale,
  mask,
  density,
  onSelect,
}: {
  day: TransactionCalendarDay
  selected: boolean
  today: boolean
  currency: string
  locale: string
  mask: (value: string) => string
  density: CalendarDensity
  onSelect: () => void
}) {
  const { t } = useTranslation()
  const isLowBalance = day.ending_balance < 0
  const detailed = density === 'detailed'
  const previewItems = detailed ? day.items.slice(0, 3) : []
  const moreCount = detailed ? Math.max(0, day.items.length - previewItems.length) : 0
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        'border-r border-b border-border p-3 text-left transition-colors hover:bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/40',
        detailed ? 'min-h-44' : 'min-h-36',
        !day.in_month && 'bg-muted/20 text-muted-foreground',
        day.in_month && isLowBalance && 'border-rose-300/80 bg-rose-50/75 shadow-[inset_0_0_0_1px_rgba(244,63,94,0.18)] dark:border-rose-500/50 dark:bg-rose-950/25',
        // Selection is a ring, not a fill, on low-balance days: tinting the cell
        // would hide the negative-balance warning exactly when the user opens it.
        selected && 'z-10 ring-2 ring-primary/70',
        selected && !isLowBalance && 'bg-primary/5 dark:bg-primary/10',
      )}
    >
      <div className="flex items-center justify-between gap-1">
        <span className={cn(
          'inline-flex size-6 shrink-0 items-center justify-center rounded-full text-sm font-bold tabular-nums',
          today && 'bg-primary text-primary-foreground',
          !today && day.in_month && 'text-foreground',
          !today && !day.in_month && 'text-muted-foreground',
        )}>
          {displayDayNumber(day.date)}
        </span>
        <CalendarBadges day={day} />
      </div>

      <div className="mt-5 flex items-center gap-1.5">
        <p
          title={mask(formatCurrency(day.ending_balance, currency, locale))}
          className={cn(
            'rounded-full border px-2 py-0.5 text-sm font-bold tabular-nums shadow-sm',
            isLowBalance
              ? 'border-rose-300 bg-rose-100 text-rose-700 dark:border-rose-500/50 dark:bg-rose-500/15 dark:text-rose-300'
              : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
          )}
        >
          {mask(compactCurrency(day.ending_balance, currency, locale))}
        </p>
      </div>

      {detailed && previewItems.length > 0 && (
        <div className="mt-3 space-y-1.5 pr-1">
          {previewItems.map((item) => (
            <DayPreviewRow
              key={`${item.kind}-${item.id ?? item.recurring_id}-${item.date}`}
              item={item}
              locale={locale}
              mask={mask}
            />
          ))}
          {moreCount > 0 && (
            <p className="truncate text-[11px] font-semibold text-muted-foreground">
              {t('transactions.calendarMoreItems', { count: moreCount })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function DayPreviewRow({ item, locale, mask }: { item: TransactionCalendarItem; locale: string; mask: (value: string) => string }) {
  const amount = signedAmount(item)
  return (
    <div
      title={`${item.description}${item.category_name ? ` · ${item.category_name}` : ''}`}
      className="flex items-center gap-1.5 rounded-md bg-background/45 px-1.5 py-1 text-[11px] shadow-sm dark:bg-background/25"
    >
      <CategoryIcon
        icon={item.category_icon ?? undefined}
        color={item.category_color ?? undefined}
        size="xs"
        // Projected items are ringed rather than given a second icon: the row is
        // only ~100px wide and an extra glyph starves the description entirely.
        className={cn(item.kind === 'projected' && 'ring-1 ring-violet-500 dark:ring-violet-400')}
      />
      <span className={cn('min-w-0 flex-1 truncate font-medium', item.kind === 'projected' ? 'text-violet-700 dark:text-violet-300' : 'text-foreground')}>
        {item.description}
      </span>
      <span className={cn('shrink-0 font-bold tabular-nums', amount >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
        {mask(`${amount >= 0 ? '+' : '−'}${compactCurrency(Math.abs(item.amount), item.currency, locale)}`)}
      </span>
    </div>
  )
}

// Markers stay on one line beside the day number. A cell header is ~100px wide and the
// date takes 28px, so the four badges are sized to fit the remainder rather than wrap
// onto a second row, which used to push the balance chip down.
function CalendarBadges({ day }: { day: TransactionCalendarDay }) {
  const { t } = useTranslation()
  return (
    <div className="flex shrink-0 items-center gap-0.5">
      {day.has_income && <BadgeDot tone="income" label={t('transactions.summaryIncome')} />}
      {day.has_expense && <BadgeDot tone="expense" label={t('transactions.summaryExpenses')} />}
      {day.has_transfer && (
        <BadgeDot tone="transfer" label={t('transactions.transfer')}>
          <ArrowLeftRight size={9} />
        </BadgeDot>
      )}
      {day.projected_count > 0 && (
        <BadgeDot tone="projected" label={t('transactions.calendarProjected')}>
          <CalendarDays size={9} />
        </BadgeDot>
      )}
    </div>
  )
}

function BadgeDot({
  tone,
  label,
  children,
}: {
  tone: CalendarMarkerTone
  label: string
  children?: ReactNode
}) {
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        'inline-flex size-3.5 shrink-0 items-center justify-center rounded border bg-background/80 shadow-sm',
        tone === 'income' && 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400',
        tone === 'expense' && 'border-rose-500/40 text-rose-600 dark:text-rose-400',
        tone === 'transfer' && 'border-sky-500/40 text-sky-600 dark:text-sky-400',
        tone === 'projected' && 'border-violet-500/40 text-violet-600 dark:text-violet-300',
      )}
    >
      {children ?? <CircleDot size={9} />}
    </span>
  )
}

function MobileDayRow({
  day,
  selected,
  currency,
  locale,
  dateLocale,
  mask,
  density,
  onSelect,
}: {
  day: TransactionCalendarDay
  selected: boolean
  currency: string
  locale: string
  dateLocale: string
  mask: (value: string) => string
  density: CalendarDensity
  onSelect: () => void
}) {
  const { t } = useTranslation()
  const isLowBalance = day.ending_balance < 0
  const previewItems = density === 'detailed' ? day.items.slice(0, 3) : []
  const moreCount = density === 'detailed' ? Math.max(0, day.items.length - previewItems.length) : 0
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full px-4 py-3 text-left transition-colors hover:bg-muted/30',
        isLowBalance && 'bg-rose-50/75 dark:bg-rose-950/25',
        selected && 'bg-primary/5 dark:bg-primary/10',
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">
            {parseLocalDate(day.date).toLocaleDateString(dateLocale, { weekday: 'short', day: 'numeric', month: 'short' })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t('transactions.calendarItemCount', { count: day.actual_count + day.projected_count })}
          </p>
        </div>
        <div className="text-right">
          <p className={cn('text-sm font-bold tabular-nums', day.ending_balance < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400')}>
            {mask(formatCurrency(day.ending_balance, currency, locale))}
          </p>
          <CalendarBadges day={day} />
        </div>
      </div>
      {previewItems.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {previewItems.map((item) => (
            <DayPreviewRow
              key={`${item.kind}-${item.id ?? item.recurring_id}-${item.date}`}
              item={item}
              locale={locale}
              mask={mask}
            />
          ))}
          {moreCount > 0 && (
            <p className="truncate text-[11px] font-semibold text-muted-foreground">
              {t('transactions.calendarMoreItems', { count: moreCount })}
            </p>
          )}
        </div>
      )}
    </button>
  )
}

function SelectedDayPanel({
  day,
  currency,
  locale,
  dateLocale,
  mask,
  onOpenTransaction,
}: {
  day?: TransactionCalendarDay
  currency: string
  locale: string
  dateLocale: string
  mask: (value: string) => string
  onOpenTransaction: (id: string) => void
}) {
  const { t } = useTranslation()
  if (!day) return null
  return (
    <aside className="bg-card rounded-xl border border-border shadow-sm overflow-hidden md:sticky md:top-4 md:max-h-[calc(100vh-7rem)] md:w-[320px] md:shrink-0 md:self-start md:flex md:flex-col lg:w-[340px]">
      <div className="px-4 py-4 border-b border-border">
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('transactions.calendarSelectedDay')}</p>
            <h3 className="truncate text-lg font-bold text-foreground">
              {parseLocalDate(day.date).toLocaleDateString(dateLocale, { weekday: 'long', day: 'numeric', month: 'long' })}
            </h3>
          </div>
          <p
            title={mask(formatCurrency(day.ending_balance, currency, locale))}
            className={cn(
              'shrink-0 text-right text-lg font-bold tabular-nums',
              day.ending_balance < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400',
            )}
          >
            {mask(formatCurrency(day.ending_balance, currency, locale))}
          </p>
        </div>
      </div>

      <div className="min-h-0 divide-y divide-border overflow-y-auto md:flex-1">
        {day.items.length === 0 ? (
          <p className="px-4 py-8 text-sm text-muted-foreground text-center">{t('transactions.calendarNoItems')}</p>
        ) : (
          day.items.map((item) => (
            <CalendarItemRow
              key={`${item.kind}-${item.id ?? item.recurring_id}-${item.date}`}
              item={item}
              locale={locale}
              mask={mask}
              onOpenTransaction={onOpenTransaction}
            />
          ))
        )}
      </div>
    </aside>
  )
}

function CalendarItemRow({
  item,
  locale,
  mask,
  onOpenTransaction,
}: {
  item: TransactionCalendarItem
  locale: string
  mask: (value: string) => string
  onOpenTransaction: (id: string) => void
}) {
  const { t } = useTranslation()
  const amount = signedAmount(item)
  const interactive = item.kind === 'actual' && !!item.id
  return (
    <button
      type="button"
      disabled={!interactive}
      onClick={() => { if (item.id) onOpenTransaction(item.id) }}
      className={cn(
        'w-full px-4 py-3 text-left flex items-center gap-3',
        interactive ? 'hover:bg-muted/50 transition-colors' : 'cursor-default',
      )}
    >
      <CategoryIcon icon={item.category_icon ?? undefined} color={item.category_color ?? undefined} size="md" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-semibold text-foreground truncate">{item.description}</p>
          {item.kind === 'projected' && (
            <span className="shrink-0 rounded-full border border-violet-500/20 bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
              {t('transactions.calendarProjected')}
            </span>
          )}
          {item.is_transfer && (
            <span className="shrink-0 text-sky-600 dark:text-sky-400"><ArrowLeftRight size={13} /></span>
          )}
        </div>
        <p className="text-xs text-muted-foreground truncate">
          {item.account_name ?? t('transactions.account')}
          {item.category_name ? ` · ${item.category_name}` : ''}
        </p>
      </div>
      <p className={cn('text-sm font-bold tabular-nums', amount >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
        {mask(`${amount >= 0 ? '+' : '−'}${formatCurrency(Math.abs(item.amount), item.currency, locale)}`)}
      </p>
    </button>
  )
}
