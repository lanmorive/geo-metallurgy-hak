/** Design tokens — single source for Tailwind and canvas (force-graph). */

export const colors = {
  surface: {
    app: '#FAFAF9',
    card: '#FFFFFF',
    border: '#E7E5E4',
  },
  brand: {
    primary: '#185FA5',
    badgeBg: '#E6F1FB',
    badgeText: '#0C447C',
  },
  semantic: {
    consensus: { bg: '#EAF3DE', text: '#3B6D11' },
    contradiction: { bg: '#FCEBEB', text: '#A32D2D' },
    gap: { bg: '#FAEEDA', text: '#854F0B' },
  },
  entity: {
    Process: '#378ADD',
    Material: '#1D9E75',
    Publication: '#7F77DD',
    Experiment: '#D85A30',
    Expert: '#888780',
    Equipment: '#D4537E',
    Property: '#EF9F27',
    Facility: '#5F5E5A',
    Organization: '#B45309',
  },
  graph: {
    edge: '#B4B2A9',
    highlight: '#185FA5',
    label: '#44403c',
  },
} as const

export const radii = {
  card: '12px',
  control: '8px',
  badge: '4px',
  pill: '999px',
} as const
