import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/** Stamp public/sw.js with this build's id and the list of emitted assets so the offline shell is precached and versioned. */
function serviceWorkerManifest(): Plugin {
  let files: string[] = []
  let outDir = 'dist'
  return {
    name: 'sw-precache',
    apply: 'build',
    configResolved: (c) => {
      outDir = c.build.outDir
    },
    writeBundle(_o, bundle) {
      files = Object.keys(bundle)
        .filter((f) => /\.(js|css)$/.test(f))
        .map((f) => `/${f}`)
    },
    closeBundle() {
      const path = join(outDir, 'sw.js')
      const list = ['/', '/offline.html', '/icon.svg', '/icon-maskable.svg', '/manifest.json', ...files]
      const src = readFileSync(path, 'utf8')
        .replace('__BUILD_ID__', Date.now().toString(36))
        .replace(/\/\*PRECACHE_START\*\/[\s\S]*?\/\*PRECACHE_END\*\//, JSON.stringify(list))
      writeFileSync(path, src)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), serviceWorkerManifest()],
  server: { proxy: { '/api': `http://localhost:${process.env.API_PORT ?? 5001}` } },
})
