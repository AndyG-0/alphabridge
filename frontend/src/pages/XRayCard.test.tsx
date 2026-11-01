import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import XRayCard from './XRayCard'

describe('XRayCard', () => {
  it('shows exposures, employer warning, overlap and coverage gaps', async () => {
    server.use(
      http.get('*/api/portfolio/xray', () =>
        HttpResponse.json({
          total: 100000,
          asset_class: { Stocks: 0.8, Cash: 0.2 },
          sector: { Technology: 0.5, Unclassified: 0.3 },
          region: { US: 1 },
          market_cap: { Large: 1 },
          overlap: [{ a: 'VOO', b: 'QQQ', overlap: 0.31, shared: 9 }],
          concentration: {
            top_names: [{ symbol: 'NVDA', weight: 0.26 }],
            hhi_named: 0.07,
            named_share: 0.4,
            employer_symbol: 'NVDA',
            employer_weight: 0.26,
            warnings: ['Employer stock NVDA is 26% of the portfolio'],
          },
          coverage: [{ symbol: 'ZZZZ', missing: ['region'] }],
          notes: '',
        }),
      ),
    )
    render(<XRayCard />)
    expect(await screen.findByText(/Employer stock NVDA is 26%/)).toBeInTheDocument()
    expect(screen.getByText('VOO / QQQ')).toBeInTheDocument()
    expect(screen.getByText(/ZZZZ \(region\)/)).toBeInTheDocument()
    expect(screen.getByText('Technology')).toBeInTheDocument()
  })
})
