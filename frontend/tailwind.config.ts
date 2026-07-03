import type { Config } from 'tailwindcss'
import { colors, radii } from './src/theme/tokens'

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: colors.surface,
        brand: colors.brand,
        semantic: colors.semantic,
        entity: colors.entity,
        graph: colors.graph,
      },
      borderRadius: {
        card: radii.card,
        control: radii.control,
        badge: radii.badge,
        pill: radii.pill,
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
