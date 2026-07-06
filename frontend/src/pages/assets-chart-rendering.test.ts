import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const __dirname = dirname(fileURLToPath(import.meta.url))
const assetsPageSource = readFileSync(join(__dirname, 'assets.tsx'), 'utf8')
const portfolioChartSource = assetsPageSource.slice(
  assetsPageSource.indexOf('function PortfolioChart'),
  assetsPageSource.indexOf('// Marker drawn on the value chart'),
)

describe('PortfolioChart rendering semantics', () => {
  it('renders wallet/asset values as unstacked line curves', () => {
    expect(portfolioChartSource).toContain('<RechartsLineChart')
    expect(portfolioChartSource).toContain('<Line')
    expect(portfolioChartSource).not.toContain('stackId')
  })

  it('documents the issue #341 stacked-area failure mode', () => {
    const values = [
      { name: 'Itaú', value: 970 },
      { name: 'Banco do Brasil', value: 30 },
    ]

    let cumulative = 0
    const stackedTopLines = values.map((wallet) => {
      cumulative += wallet.value
      return { ...wallet, plottedY: cumulative }
    })

    // In a stacked chart, the small 3% wallet is drawn at the portfolio total,
    // so its line hugs the 97% wallet instead of sitting near the baseline.
    expect(stackedTopLines[0]).toMatchObject({ name: 'Itaú', value: 970, plottedY: 970 })
    expect(stackedTopLines[1]).toMatchObject({ name: 'Banco do Brasil', value: 30, plottedY: 1000 })
    expect(stackedTopLines[1].plottedY - stackedTopLines[0].plottedY).toBe(30)
    expect(values[0].value - values[1].value).toBe(940)
  })
})
