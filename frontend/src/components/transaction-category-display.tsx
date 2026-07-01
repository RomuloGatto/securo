import { ArrowLeftRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { CategoryIcon } from '@/components/category-icon'
import type { Transaction } from '@/types'

export function TransactionCategoryDisplay({
  transaction,
  className = '',
  iconSize = 'sm',
  empty = '—',
}: {
  transaction: Pick<Transaction, 'category' | 'allocations'> | null | undefined
  className?: string
  iconSize?: 'sm' | 'md' | 'lg'
  empty?: string
}) {
  const { t } = useTranslation()
  const allocations = transaction?.allocations ?? []
  const allocationCount = allocations.length

  if (allocationCount > 0) {
    return (
      <span className={`inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground ${className}`}>
        <ArrowLeftRight size={12} />
        {t('transactions.paymentSplitBadge')}
        <span className="text-muted-foreground/70">({allocationCount})</span>
      </span>
    )
  }

  if (transaction?.category) {
    return (
      <span className={`inline-flex items-center gap-1.5 ${className}`}>
        <CategoryIcon icon={transaction.category.icon} color={transaction.category.color} size={iconSize} />
        <span className="text-sm text-muted-foreground">{transaction.category.name}</span>
      </span>
    )
  }

  return <span className={`text-muted-foreground ${className}`}>{empty}</span>
}
