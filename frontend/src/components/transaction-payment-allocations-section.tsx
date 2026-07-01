import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeftRight, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { transactions as transactionsApi } from '@/lib/api'
import { getAccountName } from '@/lib/account-utils'
import { formatCurrency } from '@/lib/format'
import { useDisplayLocale } from '@/hooks/use-display-locale'
import { CategorySelect } from '@/components/category-select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type {
  Category,
  CategoryGroup,
  Transaction,
  TransactionAllocation,
  TransactionAllocationInput,
  TransactionAllocationKind,
} from '@/types'

interface AccountOption {
  id: string
  name: string
  display_name?: string | null
  type?: string
  currency?: string
}

type CounterpartMode = 'create' | 'link'

interface AllocationRowState {
  localId: string
  kind: TransactionAllocationKind
  amount: string
  category_id: string
  transfer_account_id: string
  counterpart_mode: CounterpartMode
  counterpart_transaction_id: string
  notes: string
}

function toNumber(value: unknown): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

function formatAmountInput(value: unknown): string {
  const num = toNumber(value)
  return num > 0 ? num.toFixed(2) : ''
}

function fromExistingAllocation(allocation: TransactionAllocation): AllocationRowState {
  return {
    localId: allocation.id,
    kind: allocation.kind,
    amount: formatAmountInput(allocation.amount),
    category_id: allocation.category_id ?? '',
    transfer_account_id: allocation.transfer_account_id ?? '',
    counterpart_mode: allocation.counterpart_transaction_id && !allocation.counterpart_created ? 'link' : 'create',
    counterpart_transaction_id: allocation.counterpart_created ? '' : allocation.counterpart_transaction_id ?? '',
    notes: allocation.notes ?? '',
  }
}

function newRow(kind: TransactionAllocationKind, amount = '', categoryId = ''): AllocationRowState {
  return {
    localId: crypto.randomUUID(),
    kind,
    amount,
    category_id: kind === 'category' ? categoryId : '',
    transfer_account_id: '',
    counterpart_mode: 'create',
    counterpart_transaction_id: '',
    notes: '',
  }
}

function buildPayload(rows: AllocationRowState[]): TransactionAllocationInput[] {
  return rows.map((row) => {
    const amount = Number(row.amount)
    if (row.kind === 'category') {
      return {
        kind: 'category',
        amount,
        category_id: row.category_id || null,
        notes: row.notes.trim() || null,
      }
    }
    return {
      kind: 'transfer',
      amount,
      transfer_account_id: row.transfer_account_id || null,
      counterpart_transaction_id: row.counterpart_mode === 'link'
        ? row.counterpart_transaction_id || null
        : null,
      notes: row.notes.trim() || null,
    }
  })
}

export function TransactionPaymentAllocationsSection({
  transaction,
  amount,
  currency,
  type,
  categoryId,
  accountId,
  categories,
  categoryGroups,
  accounts,
  sharedSplitEnabled,
  hideAmounts = false,
  maskValue = '••••',
  value,
  onChange,
  onValidityChange,
}: {
  transaction: Transaction | null
  amount: number
  currency: string
  type: 'debit' | 'credit'
  categoryId: string
  accountId: string
  categories: Category[]
  categoryGroups: CategoryGroup[]
  accounts: AccountOption[]
  sharedSplitEnabled: boolean
  hideAmounts?: boolean
  maskValue?: string
  value: TransactionAllocationInput[] | null | undefined
  onChange: (next: TransactionAllocationInput[] | null) => void
  onValidityChange?: (valid: boolean) => void
}) {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const existingAllocations = transaction?.allocations ?? []
  const [dirty, setDirty] = useState(false)
  const [enabled, setEnabled] = useState(existingAllocations.length > 0 || (value !== undefined && value !== null))
  const [rows, setRows] = useState<AllocationRowState[]>(() => {
    if (existingAllocations.length > 0) return existingAllocations.map(fromExistingAllocation)
    return []
  })
  const [candidatesByRow, setCandidatesByRow] = useState<Record<string, Transaction[]>>({})
  const [loadingCandidates, setLoadingCandidates] = useState<Record<string, boolean>>({})
  const rowsRef = useRef(rows)

  useEffect(() => {
    rowsRef.current = rows
  }, [rows])

  const targetAmount = Math.abs(Number.isFinite(amount) ? amount : 0)
  const allocated = useMemo(
    () => rows.reduce((sum, row) => sum + (Number(row.amount) || 0), 0),
    [rows],
  )
  const remaining = targetAmount - allocated
  const displayAmount = (value: number, currencyCode = currency) => (
    hideAmounts ? maskValue : formatCurrency(value, currencyCode, locale)
  )

  const clearCandidatesForRow = (localId: string) => {
    setCandidatesByRow((prev) => {
      if (!(localId in prev)) return prev
      const next = { ...prev }
      delete next[localId]
      return next
    })
  }

  const updateRow = (localId: string, patch: Partial<AllocationRowState>) => {
    setDirty(true)
    setRows((prev) => prev.map((row) => row.localId === localId ? { ...row, ...patch } : row))
  }

  const addRow = (kind: TransactionAllocationKind) => {
    const fill = Math.max(remaining, 0)
    setDirty(true)
    setRows((prev) => [...prev, newRow(kind, fill > 0 ? fill.toFixed(2) : '', categoryId)])
  }

  const autofillRemaining = (localId: string) => {
    const otherTotal = rows
      .filter((row) => row.localId !== localId)
      .reduce((sum, row) => sum + (Number(row.amount) || 0), 0)
    updateRow(localId, { amount: Math.max(targetAmount - otherTotal, 0).toFixed(2) })
  }

  const enableDefaultRows = () => {
    setDirty(true)
    setEnabled(true)
    if (rows.length === 0) {
      setRows([newRow('category', targetAmount > 0 ? targetAmount.toFixed(2) : '', categoryId)])
    }
  }

  const loadCandidates = async (row: AllocationRowState) => {
    if (!transaction?.id || !row.transfer_account_id || !(Number(row.amount) > 0)) return
    const requestAccountId = row.transfer_account_id
    const requestAmount = row.amount
    setLoadingCandidates((prev) => ({ ...prev, [row.localId]: true }))
    try {
      const candidates = await transactionsApi.allocationCandidates(transaction.id, {
        transfer_account_id: requestAccountId,
        amount: Number(requestAmount),
        limit: 20,
        window_days: 30,
      })
      setCandidatesByRow((prev) => {
        const current = rowsRef.current.find((item) => item.localId === row.localId)
        if (
          !current
          || current.transfer_account_id !== requestAccountId
          || current.amount !== requestAmount
        ) {
          return prev
        }
        return { ...prev, [row.localId]: candidates }
      })
    } catch {
      toast.error(t('transactions.paymentSplitCandidatesError', 'Could not load counterpart candidates'))
    } finally {
      setLoadingCandidates((prev) => ({ ...prev, [row.localId]: false }))
    }
  }

  useEffect(() => {
    if (!dirty) return
    if (!enabled) {
      onChange(null)
      return
    }
    onChange(buildPayload(rows))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, enabled, rows])

  const validation = (() => {
    if (!enabled) return { valid: true, message: '' }
    if (sharedSplitEnabled) {
      return {
        valid: false,
        message: t(
          'transactions.paymentSplitSharedConflict',
          'Payment splits cannot be combined with shared/group splits yet.',
        ),
      }
    }
    if (rows.length === 0) {
      return { valid: false, message: t('transactions.paymentSplitNeedsRows', 'Add at least one split line.') }
    }
    if (targetAmount <= 0) {
      return { valid: false, message: t('transactions.paymentSplitNeedsAmount', 'Enter the transaction amount first.') }
    }
    for (const row of rows) {
      if (!(Number(row.amount) > 0)) {
        return { valid: false, message: t('transactions.paymentSplitPositiveAmounts', 'All split lines need a positive amount.') }
      }
      if (row.kind === 'category' && !row.category_id) {
        return { valid: false, message: t('transactions.paymentSplitNeedsCategory', 'Category lines need a category.') }
      }
      if (row.kind === 'transfer') {
        if (!row.transfer_account_id) {
          return { valid: false, message: t('transactions.paymentSplitNeedsAccount', 'Transfer lines need a target account.') }
        }
        if (row.transfer_account_id === accountId) {
          return { valid: false, message: t('transactions.paymentSplitSameAccount', 'Transfer lines must target another account.') }
        }
        const target = accounts.find((account) => account.id === row.transfer_account_id)
        if (target?.currency && target.currency !== currency) {
          return {
            valid: false,
            message: t(
              'transactions.paymentSplitSameCurrency',
              'Transfer account currency must match this transaction.',
            ),
          }
        }
        if (row.counterpart_mode === 'link' && !row.counterpart_transaction_id) {
          return { valid: false, message: t('transactions.paymentSplitNeedsCounterpart', 'Pick the existing counterpart transaction.') }
        }
      }
    }
    if (Math.abs(allocated - targetAmount) >= 0.005) {
      return {
        valid: false,
        message: t('transactions.paymentSplitSumMismatch', {
          defaultValue: 'Split lines must sum to {{target}}. Remaining: {{remaining}}.',
          target: displayAmount(targetAmount),
          remaining: displayAmount(Math.abs(remaining)),
        }),
      }
    }
    return { valid: true, message: '' }
  })()

  useEffect(() => {
    onValidityChange?.(validation.valid)
  }, [onValidityChange, validation.valid])

  return (
    <div className="space-y-3 pt-2 border-t border-border">
      <label className="text-sm font-medium inline-flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => {
            setDirty(true)
            if (event.target.checked) enableDefaultRows()
            else setEnabled(false)
          }}
          className="h-4 w-4 rounded border-border accent-primary"
        />
        <ArrowLeftRight size={14} />
        {t('transactions.paymentSplitTitle', 'Split payment')}
      </label>

      {enabled && (
        <div className="space-y-3 pl-6">
          <p className="text-xs text-muted-foreground">
            {t(
              'transactions.paymentSplitHint',
              'Use category lines for spending/income and transfer lines for amounts moved to another account.',
            )}
          </p>

          <div className="space-y-2">
            {rows.map((row, index) => {
              const candidates = candidatesByRow[row.localId] ?? []
              const rowAmount = Number(row.amount) || 0
              return (
                <div key={row.localId} className="rounded-md border bg-muted/20 p-3 space-y-2">
                  <div className="grid grid-cols-[1fr_120px_32px] gap-2 items-end">
                    <div className="space-y-1">
                      <Label className="text-xs">{t('transactions.paymentSplitLineType', 'Line type')}</Label>
                      <select
                        className="w-full border border-border rounded-md px-2 py-1.5 text-sm bg-background"
                        value={row.kind}
                        onChange={(event) => {
                          clearCandidatesForRow(row.localId)
                          updateRow(row.localId, {
                            kind: event.target.value as TransactionAllocationKind,
                            category_id: event.target.value === 'category' ? categoryId : '',
                            transfer_account_id: '',
                            counterpart_mode: 'create',
                            counterpart_transaction_id: '',
                          })
                        }}
                      >
                        <option value="category">{t('transactions.paymentSplitCategory', 'Category')}</option>
                        <option value="transfer">{t('transactions.paymentSplitTransfer', 'Transfer')}</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">{t('transactions.amount')}</Label>
                      {hideAmounts ? (
                        <Input
                          type="text"
                          value={maskValue}
                          readOnly
                          tabIndex={-1}
                          className="bg-muted/40 text-muted-foreground cursor-default select-none"
                        />
                      ) : (
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          value={row.amount}
                          onChange={(event) => {
                            clearCandidatesForRow(row.localId)
                            updateRow(row.localId, {
                              amount: event.target.value,
                              counterpart_transaction_id: '',
                            })
                          }}
                        />
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-9 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => {
                        setDirty(true)
                        setRows((prev) => prev.filter((item) => item.localId !== row.localId))
                      }}
                      aria-label={t('common.delete')}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>

                  {row.kind === 'category' ? (
                    <div className="space-y-1">
                      <Label className="text-xs">{t('transactions.category')}</Label>
                      <CategorySelect
                        value={row.category_id}
                        onChange={(next) => updateRow(row.localId, { category_id: next })}
                        categories={categories}
                        groups={categoryGroups}
                        allowNone={false}
                      />
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-xs">{t('transactions.paymentSplitTargetAccount', 'Target account')}</Label>
                          <select
                            className="w-full border border-border rounded-md px-2 py-1.5 text-sm bg-background"
                            value={row.transfer_account_id}
                            onChange={(event) => {
                              clearCandidatesForRow(row.localId)
                              updateRow(row.localId, {
                                transfer_account_id: event.target.value,
                                counterpart_transaction_id: '',
                              })
                            }}
                          >
                            <option value="">{t('transactions.selectAccount', 'Select account')}</option>
                            {accounts
                              .filter((account) => account.id !== accountId)
                              .map((account) => (
                                <option key={account.id} value={account.id}>
                                  {getAccountName(account)}{account.currency ? ` · ${account.currency}` : ''}
                                </option>
                              ))}
                          </select>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">{t('transactions.paymentSplitCounterpart', 'Counterpart')}</Label>
                          <select
                            className="w-full border border-border rounded-md px-2 py-1.5 text-sm bg-background"
                            value={row.counterpart_mode}
                            onChange={(event) => {
                              clearCandidatesForRow(row.localId)
                              updateRow(row.localId, {
                                counterpart_mode: event.target.value as CounterpartMode,
                                counterpart_transaction_id: '',
                              })
                            }}
                          >
                            <option value="create">{t('transactions.paymentSplitCreateCounterpart', 'Create new')}</option>
                            <option value="link" disabled={!transaction?.id}>
                              {t('transactions.paymentSplitLinkCounterpart', 'Link existing')}
                            </option>
                          </select>
                        </div>
                      </div>

                      {row.counterpart_mode === 'link' && (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <Label className="text-xs">{t('transactions.paymentSplitExistingCounterpart', 'Existing transaction')}</Label>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              disabled={!transaction?.id || !row.transfer_account_id || rowAmount <= 0 || loadingCandidates[row.localId]}
                              onClick={() => loadCandidates(row)}
                            >
                              {loadingCandidates[row.localId]
                                ? t('common.loading')
                                : t('transactions.paymentSplitFindMatches', 'Find matches')}
                            </Button>
                          </div>
                          {!transaction?.id ? (
                            <p className="text-xs text-muted-foreground">
                              {t('transactions.paymentSplitSaveFirst', 'Save the transaction first to link an existing counterpart.')}
                            </p>
                          ) : (
                            <select
                              className="w-full border border-border rounded-md px-2 py-1.5 text-sm bg-background"
                              value={row.counterpart_transaction_id}
                              onFocus={() => {
                                if (!candidatesByRow[row.localId]) void loadCandidates(row)
                              }}
                              onChange={(event) => updateRow(row.localId, { counterpart_transaction_id: event.target.value })}
                            >
                              <option value="">
                                {candidates.length === 0
                                  ? t('transactions.paymentSplitNoMatches', 'No matches loaded')
                                  : t('transactions.paymentSplitChooseMatch', 'Choose a matching transaction')}
                              </option>
                              {candidates.map((candidate) => (
                                <option key={candidate.id} value={candidate.id}>
                                  {candidate.date} ·{' '}
                                  {displayAmount(Math.abs(candidate.amount), candidate.currency)} ·{' '}
                                  {candidate.description}
                                </option>
                              ))}
                            </select>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-2">
                    <Input
                      value={row.notes}
                      onChange={(event) => updateRow(row.localId, { notes: event.target.value })}
                      placeholder={t('transactions.notes')}
                    />
                    <Button type="button" variant="outline" size="sm" onClick={() => autofillRemaining(row.localId)}>
                      {t('transactions.paymentSplitFillRemaining', 'Fill')}
                    </Button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    #{index + 1} · {type === 'debit' ? t('transactions.expense') : t('transactions.income')}
                  </p>
                </div>
              )
            })}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" className="gap-1" onClick={() => addRow('category')}>
              <Plus size={14} /> {t('transactions.paymentSplitAddCategory', 'Add category line')}
            </Button>
            <Button type="button" variant="outline" size="sm" className="gap-1" onClick={() => addRow('transfer')}>
              <Plus size={14} /> {t('transactions.paymentSplitAddTransfer', 'Add transfer line')}
            </Button>
          </div>

          <div className="text-xs">
            <span className={validation.valid ? 'text-emerald-600' : 'text-amber-600'}>
              {t('transactions.paymentSplitAllocated', {
                defaultValue: 'Allocated {{allocated}} of {{target}} (remaining {{remaining}})',
                allocated: displayAmount(allocated),
                target: displayAmount(targetAmount),
                remaining: displayAmount(Math.abs(remaining)),
              })}
            </span>
            {!validation.valid && validation.message && (
              <p className="mt-1 text-amber-600">{validation.message}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
