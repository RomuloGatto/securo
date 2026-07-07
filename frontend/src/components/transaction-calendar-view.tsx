import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeftRight, CalendarDays, Check, ChevronDown, CircleDot, Minus, Plus } from 'lucide-react'
import type { Account, TransactionCalendarDay, TransactionCalendarItem, TransactionCalendarResponse } from '@/types'
import { Skeleton } from '@/components/ui/skeleton'
import { CategoryIcon } from '@/components/category-icon'
import { MonthStepper } from '@/components/month-stepper'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
  month,
  onMonthChange,
  selectedAccountId,
  onAccountScopeChange,
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
  month: string
  onMonthChange: (yearMonth: string) => void
  selectedAccountId: string | null
  onAccountScopeChange: (accountId: string | null) => void
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
    if (selectedAccountId) {
      const account = accounts.find((a) => a.id === selectedAccountId)
      return account?.display_name || account?.name || t('transactions.calendarOneAccount')
    }
    return t('transactions.calendarAllAccounts')
  }, [accounts, selectedAccountId, t])

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
          <div className="flex flex-wrap items-center justify-end gap-2">
            <MonthStepper
              value={month}
              onChange={onMonthChange}
              locale={dateLocale}
              prevLabel={t('transactions.monthPrevious')}
              nextLabel={t('transactions.monthNext')}
            />
            <AccountScopeSelect
              accounts={accounts}
              selectedAccountId={selectedAccountId}
              label={accountLabel}
              allLabel={t('transactions.calendarAllAccounts')}
              onChange={onAccountScopeChange}
            />
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
              canWrite={canWrite}
              onSelect={() => setSelectedDate(day.date)}
              onAddTransaction={onAddTransaction}
              onTransfer={onTransfer}
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

function accountDisplayName(account: Account) {
  return account.display_name || account.name
}

function AccountScopeSelect({
  accounts,
  selectedAccountId,
  label,
  allLabel,
  onChange,
}: {
  accounts: Account[]
  selectedAccountId: string | null
  label: string
  allLabel: string
  onChange: (accountId: string | null) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex h-8 max-w-[220px] items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <span className="truncate">{label}</span>
          <ChevronDown size={14} className="shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuItem onSelect={() => onChange(null)} className="gap-2">
          <span className="min-w-0 flex-1 truncate">{allLabel}</span>
          {!selectedAccountId && <Check size={14} className="text-primary" />}
        </DropdownMenuItem>
        {accounts.map((account) => {
          const selected = selectedAccountId === account.id
          return (
            <DropdownMenuItem key={account.id} onSelect={() => onChange(selected ? null : account.id)} className="gap-2">
              <span className="min-w-0 flex-1 truncate">{accountDisplayName(account)}</span>
              {account.currency && (
                <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground/70">
                  {account.currency}
                </span>
              )}
              {selected && <Check size={14} className="text-primary" />}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function DayCell({
  day,
  selected,
  today,
  currency,
  locale,
  mask,
  canWrite,
  onSelect,
  onAddTransaction,
  onTransfer,
}: {
  day: TransactionCalendarDay
  selected: boolean
  today: boolean
  currency: string
  locale: string
  mask: (value: string) => string
  canWrite: boolean
  onSelect: () => void
  onAddTransaction: (date: string, type: 'credit' | 'debit', accountId?: string | null) => void
  onTransfer: (date: string) => void
}) {
  const { t } = useTranslation()
  const primaryAccountId = day.items.find((item) => item.account_id)?.account_id
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
        <CalendarBadges day={day} />
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

      {selected && canWrite && (
        <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg border border-border/80 bg-background/85 p-1 shadow-sm backdrop-blur dark:border-slate-600/70 dark:bg-slate-950/80 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.12),0_10px_24px_rgba(0,0,0,0.4)]">
          <QuickAction label={t('transactions.calendarAddIncome')} onClick={() => onAddTransaction(day.date, 'credit', primaryAccountId)} tone="income">
            <Plus size={14} />
          </QuickAction>
          <QuickAction label={t('transactions.calendarAddExpense')} onClick={() => onAddTransaction(day.date, 'debit', primaryAccountId)} tone="expense">
            <Minus size={14} />
          </QuickAction>
          <QuickAction label={t('transactions.transfer')} onClick={() => onTransfer(day.date)} tone="transfer">
            <ArrowLeftRight size={14} />
          </QuickAction>
        </div>
      )}

    </div>
  )
}

function QuickAction({
  label,
  tone,
  onClick,
  children,
}: {
  label: string
  tone: 'income' | 'expense' | 'transfer'
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation()
        onClick()
      }}
      className={cn(
        'inline-flex h-7 items-center justify-center rounded-md border border-border/60 bg-background/70 text-xs font-semibold shadow-sm transition-colors hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary/40 dark:border-slate-600/60 dark:bg-slate-900/80 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] dark:hover:bg-slate-800',
        tone === 'income' && 'text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300',
        tone === 'expense' && 'text-rose-600 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300',
        tone === 'transfer' && 'text-sky-600 hover:text-sky-700 dark:text-sky-400 dark:hover:text-sky-300',
      )}
    >
      {children}
    </button>
  )
}

function CalendarBadges({ day }: { day: TransactionCalendarDay }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {day.has_income && <BadgeDot tone="income" label={t('transactions.summaryIncome')} />}
      {day.has_expense && <BadgeDot tone="expense" label={t('transactions.summaryExpenses')} />}
      {day.has_transfer && (
        <BadgeDot tone="transfer" label={t('transactions.transfer')}>
          <ArrowLeftRight size={12} />
        </BadgeDot>
      )}
      {day.projected_count > 0 && <BadgeDot tone="projected" label={t('transactions.calendarProjected')} />}
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
        <CalendarBadges day={day} />
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
    <aside className="bg-card rounded-xl border border-border shadow-sm overflow-hidden md:sticky md:top-4 md:max-h-[calc(100vh-7rem)] md:w-[320px] md:shrink-0 md:self-start md:flex md:flex-col lg:w-[340px]">
      <div className="px-4 py-4 border-b border-border">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('transactions.calendarSelectedDay')}</p>
        <h3 className="text-lg font-bold text-foreground">
          {parseLocalDate(day.date).toLocaleDateString(dateLocale, { weekday: 'long', day: 'numeric', month: 'long' })}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('transactions.calendarEndBalance')}: <span className="font-semibold text-foreground tabular-nums">{mask(formatCurrency(day.ending_balance, currency, locale))}</span>
        </p>
      </div>

      <div className="space-y-2 p-4 border-b border-border">
        <SummaryPill
          label={t('transactions.summaryIncome')}
          value={day.income}
          currency={currency}
          locale={locale}
          mask={mask}
          className="text-emerald-600 dark:text-emerald-400"
          actionLabel={t('transactions.calendarAddIncome')}
          actionIcon={<Plus size={14} />}
          actionTone="income"
          onAction={canWrite ? () => onAddTransaction(day.date, 'credit', primaryAccountId) : undefined}
        />
        <SummaryPill
          label={t('transactions.summaryExpenses')}
          value={day.expense}
          currency={currency}
          locale={locale}
          mask={mask}
          className="text-rose-600 dark:text-rose-400"
          actionLabel={t('transactions.calendarAddExpense')}
          actionIcon={<Minus size={14} />}
          actionTone="expense"
          onAction={canWrite ? () => onAddTransaction(day.date, 'debit', primaryAccountId) : undefined}
        />
        <SummaryPill
          label={t('transactions.transfer')}
          value={day.transfer_net}
          currency={currency}
          locale={locale}
          mask={mask}
          className="text-sky-600 dark:text-sky-400"
          actionLabel={t('transactions.transfer')}
          actionIcon={<ArrowLeftRight size={14} />}
          actionTone="transfer"
          onAction={canWrite ? () => onTransfer(day.date) : undefined}
        />
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

function SummaryPill({
  label,
  value,
  currency,
  locale,
  mask,
  className,
  actionLabel,
  actionIcon,
  actionTone,
  onAction,
}: {
  label: string
  value: number
  currency: string
  locale: string
  mask: (value: string) => string
  className: string
  actionLabel?: string
  actionIcon?: ReactNode
  actionTone?: 'income' | 'expense' | 'transfer'
  onAction?: () => void
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-background/60 px-3 py-2 dark:bg-muted/20">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground truncate">{label}</p>
          <p className={cn('text-sm font-bold tabular-nums truncate', className)}>{mask(formatCurrency(Math.abs(value), currency, locale))}</p>
        </div>
        {onAction && actionLabel && actionIcon && actionTone && (
          <button
            type="button"
            title={actionLabel}
            aria-label={actionLabel}
            onClick={onAction}
            className={cn(
              'inline-flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground shadow-sm transition-colors hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary/40 dark:border-slate-600/70 dark:bg-slate-950/70 dark:hover:bg-slate-800',
              actionTone === 'income' && 'text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300',
              actionTone === 'expense' && 'text-rose-600 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300',
              actionTone === 'transfer' && 'text-sky-600 hover:text-sky-700 dark:text-sky-400 dark:hover:text-sky-300',
            )}
          >
            {actionIcon}
          </button>
        )}
      </div>
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
