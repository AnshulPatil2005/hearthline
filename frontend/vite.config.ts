import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Bryntum's advice: pre-bundle its packages so the dev server never loads the shared core twice.
  optimizeDeps: {
    include: [
      '@bryntum/core-thin',
      '@bryntum/grid-thin',
      '@bryntum/scheduler-thin',
      '@bryntum/schedulerpro-thin',
      '@bryntum/gantt-thin',
      '@bryntum/calendar-thin',
      '@bryntum/taskboard-thin',
      '@bryntum/gantt-react-thin',
      '@bryntum/schedulerpro-react-thin',
      '@bryntum/calendar-react-thin',
      '@bryntum/taskboard-react-thin',
    ],
  },
})
