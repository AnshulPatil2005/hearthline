import { AgChartsEnterpriseModule } from 'ag-charts-enterprise'
import type { AgChartTheme } from 'ag-charts-types'
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import { AllEnterpriseModule, LicenseManager } from 'ag-grid-enterprise'

// AG Charts powers integrated charts (select cells, right-click, chart) and the sparkline cells.
ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule.with(AgChartsEnterpriseModule)])

// Without a key AG Grid Enterprise runs in trial mode (watermark); set VITE_AG_GRID_LICENSE when we have one.
const license = import.meta.env.VITE_AG_GRID_LICENSE as string | undefined
if (license) LicenseManager.setLicenseKey(license)

// Colors come from our CSS variables, so the grid follows light/dark mode with the rest of the app.
export const gridTheme = themeQuartz.withParams({
  accentColor: 'var(--ember)',
  backgroundColor: 'var(--surface)',
  foregroundColor: 'var(--ink)',
  borderColor: 'var(--line)',
  chromeBackgroundColor: 'var(--sunken)',
  headerTextColor: 'var(--ink)',
  headerFontWeight: 600,
  oddRowBackgroundColor: 'var(--surface)',
  fontFamily: 'inherit',
  // Like the panels: square corners and an ink rule along the top of the header
  wrapperBorderRadius: 4,
  borderRadius: 3,
  headerBackgroundColor: 'var(--paper)',
  wrapperBorder: { color: 'var(--line)' },
  headerRowBorder: { color: 'var(--ink)', width: 1 },
})

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Grid options that draw integrated charts in the app's type and colours, light or dark. `fills` are CSS variables,
 * one per series in order; without them the chart keeps AG Charts' palette. */
export function chartColors(fills: string[] = []) {
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const colors = fills.map(cssVar)
  const theme: AgChartTheme = {
    baseTheme: dark ? 'ag-default-dark' : 'ag-default',
    ...(colors.length ? { palette: { fills: colors, strokes: colors } } : {}),
    params: {
      fontFamily: 'Inter Variable, system-ui, sans-serif',
      backgroundColor: cssVar('--surface'),
      foregroundColor: cssVar('--ink'),
    },
  }
  return { chartThemes: ['hearthline'], customChartThemes: { hearthline: theme } }
}
