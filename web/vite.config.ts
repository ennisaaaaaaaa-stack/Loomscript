import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// `npm run build:single` 打成单个 HTML（fixtures 内联），方便发给队友直接打开
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'single' ? [viteSingleFile()] : [])],
  build: mode === 'single' ? { outDir: 'dist-single' } : {},
  // fixtures 直接读仓库上层的 demos/ 和 contracts/
  server: { fs: { allow: ['..'] } },
}))
