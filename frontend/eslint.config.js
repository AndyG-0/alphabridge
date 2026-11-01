import js from '@eslint/js'
import globals from 'globals'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['public', 'dist', 'coverage', 'playwright-report', 'test-results'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { 'react-hooks': reactHooks },
    // set-state-in-effect is pre-existing across pages; fix gradually, then flip to error.
    rules: { ...reactHooks.configs.recommended.rules, 'react-hooks/set-state-in-effect': 'warn' },
  },
  { rules: { 'jsx-a11y/label-has-associated-control': ['error', { depth: 3 }] } },
  { files: ['*.config.{js,ts}'], languageOptions: { globals: { ...globals.node } } },
)
