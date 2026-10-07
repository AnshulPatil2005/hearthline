import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import { AllEnterpriseModule, LicenseManager } from 'ag-grid-enterprise'

ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule])

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
  headerTextColor: 'var(--ink-soft)',
  oddRowBackgroundColor: 'var(--surface)',
  fontFamily: 'inherit',
  wrapperBorderRadius: 12,
})
