import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeftRight, CalendarDays, CircleDot, Minus, Plus } from 'lucide-react'
import type { Account, TransactionCalendarDay, TransactionCalendarItem, TransactionCalendarResponse } from '@/types'
import { Button } from '@/components/ui/button'
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

export function TransactionCalendarView({
  calendar,
  isLoading,
  accounts,
  locale,
  dateLocale,
  mask,
  canWrite,
  onAddTransaction,
  onTransfer,
  onOpenTransaction,
}: {
  calendar?: TransactionCalendarResponse
  isLoading: boolean
  accounts: Account[]
  locale: string
  dateLocale: string
  mask: (value: string) => string
  canWrite: boolean
  onAddTransaction: (date: string, type: 'credit' | 'debit', accountId?: string | null) => void
  onTransfer: (date: string) => void
  onOpenTransaction: (id: string) => void
}) {
  const { t } = useTranslation()
  const [selectedDate, setSelectedDate] = useState<string>('')

  useEffect(() => {
    if (!calendar?.days.length) return
    const today = todayIso()
    const inCalendarToday = calendar.days.find((day) => day.date === today)
    const firstInMonth = calendar.days.find((day) => day.in_month)
    setSelectedDate((prev) => {
      if (prev && calendar.days.some((day) => day.date === prev)) return prev
      return (inCalendarToday ?? firstInMonth ?? calendar.days[0]).date
    })
  }, [calendar])

  const accountLabel = useMemo(() => {
    const ids = calendar?.account_ids
    if (ids && ids.length === 1) {
      const account = accounts.find((a) => a.id === ids[0])
      return account?.display_name || account?.name || t('transactions.calendarOneAccount')
    }
    if (ids && ids.length > 1) return t('transactions.calendarAccountCount', { count: ids.length })
    return t('transactions.calendarAllAccounts')
  }, [accounts, calendar?.account_ids, t])

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
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr),minmax(280px,340px)] mb-4">
      <section className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <div className="px-4 sm:px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <CalendarDays className="size-3.5" />
              {t('transactions.calendar')}
            </p>
            <h2 className="text-xl font-bold text-foreground">
              {parseLocalDate(`${calendar.month}-02`).toLocaleDateString(dateLocale, { month: 'long', year: 'numeric' })}
            </h2>
          </div>
          <div className="rounded-lg border border-border bg-muted/30 px-3 py-1.5 text-sm font-medium text-muted-foreground">
            {accountLabel}
          </div>
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
              onSelect={() => setSelectedDate(day.date)}
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
              onSelect={() => setSelectedDate(day.date)}
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
        canWrite={canWrite}
        onAddTransaction={onAddTransaction}
        onTransfer={onTransfer}
        onOpenTransaction={onOpenTransaction}
      />
    </div>
  )
}

function DayCell({
  day,
  selected,
  today,
  currency,
  locale,
  mask,
  onSelect,
}: {
  day: TransactionCalendarDay
  selected: boolean
  today: boolean
  currency: string
  locale: string
  mask: (value: string) => string
  onSelect: () => void
}) {
  const { t } = useTranslation()
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
        'relative min-h-36 border-r border-b border-border p-3 text-left transition-colors hover:bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/40',
        !day.in_month && 'bg-muted/20 text-muted-foreground',
        selected && 'z-10 bg-primary/5 ring-2 ring-primary/70 dark:bg-primary/10',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className={cn(
          'inline-flex size-7 items-center justify-center rounded-full text-sm font-bold tabular-nums',
          today && 'bg-primary text-primary-foreground',
          !today && day.in_month && 'text-foreground',
          !today && !day.in_month && 'text-muted-foreground',
        )}>
          {displayDayNumber(day.date)}
        </span>
        <CalendarBadges day={day} currency={currency} locale={locale} mask={mask} />
      </div>

      <div className="mt-5 space-y-1">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t('transactions.calendarEndBalance')}
        </p>
        <p className={cn(
          'text-sm font-bold tabular-nums',
          day.ending_balance < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-emerald-600 dark:text-emerald-400',
        )}>
          {mask(compactCurrency(day.ending_balance, currency, locale))}
        </p>
      </div>

      {(day.actual_count > 0 || day.projected_count > 0) && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          {t('transactions.calendarItemCount', { count: day.actual_count + day.projected_count })}
          {day.projected_count > 0 && ` · ${t('transactions.calendarProjectedCount', { count: day.projected_count })}`}
        </p>
      )}

    </div>
  )
}

function CalendarBadges({
  day,
  currency,
  locale,
  mask,
}: {
  day: TransactionCalendarDay
  currency: string
  locale: string
  mask: (value: string) => string
}) {
  const { t } = useTranslation()
  const moneyTooltip = (label: string, value: number) => `${label}: ${mask(formatCurrency(Math.abs(value), currency, locale))}`
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {day.has_income && <BadgeDot tone="income" label={moneyTooltip(t('transactions.summaryIncome'), day.income)} />}
      {day.has_expense && <BadgeDot tone="expense" label={moneyTooltip(t('transactions.summaryExpenses'), day.expense)} />}
      {day.has_transfer && (
        <BadgeDot tone="transfer" label={moneyTooltip(t('transactions.transfer'), day.transfer_net)}>
          <ArrowLeftRight size={12} />
        </BadgeDot>
      )}
      {day.projected_count > 0 && <BadgeDot tone="projected" label={t('transactions.calendarProjectedCount', { count: day.projected_count })} />}
    </div>
  )
}

function BadgeDot({
  tone,
  label,
  children,
}: {
  tone: 'income' | 'expense' | 'transfer' | 'projected'
  label: string
  children?: ReactNode
}) {
  return (
    <span
      title={label}
      className={cn(
        'inline-flex size-5 items-center justify-center rounded-md border border-border bg-background/80 shadow-sm backdrop-blur',
        tone === 'income' && 'text-emerald-600 dark:text-emerald-400',
        tone === 'expense' && 'text-rose-600 dark:text-rose-400',
        tone === 'transfer' && 'text-sky-600 dark:text-sky-400',
        tone === 'projected' && 'text-violet-600 dark:text-violet-300',
      )}
    >
      {children ?? <CircleDot size={11} />}
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
  onSelect,
}: {
  day: TransactionCalendarDay
  selected: boolean
  currency: string
  locale: string
  dateLocale: string
  mask: (value: string) => string
  onSelect: () => void
}) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn('w-full px-4 py-3 text-left flex items-center justify-between gap-3 transition-colors hover:bg-muted/30', selected && 'bg-primary/5 dark:bg-primary/10')}
    >
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
        <CalendarBadges day={day} currency={currency} locale={locale} mask={mask} />
      </div>
    </button>
  )
}

function SelectedDayPanel({
  day,
  currency,
  locale,
  dateLocale,
  mask,
  canWrite,
  onAddTransaction,
  onTransfer,
  onOpenTransaction,
}: {
  day?: TransactionCalendarDay
  currency: string
  locale: string
  dateLocale: string
  mask: (value: string) => string
  canWrite: boolean
  onAddTransaction: (date: string, type: 'credit' | 'debit', accountId?: string | null) => void
  onTransfer: (date: string) => void
  onOpenTransaction: (id: string) => void
}) {
  const { t } = useTranslation()
  if (!day) return null
  const primaryAccountId = day.items.find((item) => item.account_id)?.account_id
  return (
    <aside className="bg-card rounded-xl border border-border shadow-sm overflow-hidden md:sticky md:top-4 md:self-start md:max-h-[calc(100vh-7rem)] md:flex md:flex-col">
      <div className="px-4 py-4 border-b border-border">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('transactions.calendarSelectedDay')}</p>
        <h3 className="text-lg font-bold text-foreground">
          {parseLocalDate(day.date).toLocaleDateString(dateLocale, { weekday: 'long', day: 'numeric', month: 'long' })}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('transactions.calendarEndBalance')}: <span className="font-semibold text-foreground tabular-nums">{mask(formatCurrency(day.ending_balance, currency, locale))}</span>
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2 p-4 border-b border-border">
        <SummaryPill label={t('transactions.summaryIncome')} value={day.income} currency={currency} locale={locale} mask={mask} className="text-emerald-600 dark:text-emerald-400" />
        <SummaryPill label={t('transactions.summaryExpenses')} value={day.expense} currency={currency} locale={locale} mask={mask} className="text-rose-600 dark:text-rose-400" />
        <SummaryPill label={t('transactions.transfer')} value={day.transfer_net} currency={currency} locale={locale} mask={mask} className="text-sky-600 dark:text-sky-400" />
      </div>

      {canWrite && (
        <div className="grid grid-cols-1 gap-2 p-4 border-b border-border sm:grid-cols-3 md:grid-cols-1">
          <Button size="sm" variant="outline" onClick={() => onAddTransaction(day.date, 'credit', primaryAccountId)} className="justify-start gap-2 border-border bg-background hover:bg-muted hover:text-foreground">
            <Plus size={14} className="text-emerald-600 dark:text-emerald-400" /> {t('transactions.income')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => onAddTransaction(day.date, 'debit', primaryAccountId)} className="justify-start gap-2 border-border bg-background hover:bg-muted hover:text-foreground">
            <Minus size={14} className="text-rose-600 dark:text-rose-400" /> {t('transactions.expense')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => onTransfer(day.date)} className="justify-start gap-2 border-border bg-background hover:bg-muted hover:text-foreground">
            <ArrowLeftRight size={14} className="text-sky-600 dark:text-sky-400" /> {t('transactions.transfer')}
          </Button>
        </div>
      )}

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

function SummaryPill({
  label,
  value,
  currency,
  locale,
  mask,
  className,
}: {
  label: string
  value: number
  currency: string
  locale: string
  mask: (value: string) => string
  className: string
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-background/60 px-2 py-2 dark:bg-muted/20">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground truncate">{label}</p>
      <p className={cn('text-xs font-bold tabular-nums truncate', className)}>{mask(formatCurrency(Math.abs(value), currency, locale))}</p>
    </div>
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
