import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['editor_src/__tests__/**/*.test.js'],
  },
})
