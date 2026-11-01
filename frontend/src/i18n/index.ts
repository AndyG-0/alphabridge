import en from './en.json'

export type MessageKey = keyof typeof en

/** Look up a UI string. Keys are checked at compile time; `{name}` placeholders are filled from `vars`. */
export function t(key: MessageKey, vars?: Record<string, string | number>): string {
  const msg: string = en[key] ?? key
  return vars ? msg.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? `{${k}}`)) : msg
}
