import type { ComponentPropsWithoutRef, ElementType } from 'react'
import ReactMarkdown, { type Components, type ExtraProps } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Styled with the app's slate/emerald scale so the light-theme remap in index.css applies.
// Raw HTML in the source is not rendered (react-markdown default), so model output can't inject markup.

/** A markdown element rendered as `Tag` with `cls` merged ahead of any class markdown supplies. */
function styled<T extends ElementType>(Tag: T, cls: string, extra: Partial<ComponentPropsWithoutRef<T>> = {}) {
  const El = Tag as ElementType
  return function Styled(props: ComponentPropsWithoutRef<T> & ExtraProps) {
    const { node: _node, className, children, ...rest } = props as ComponentPropsWithoutRef<'div'> & ExtraProps
    void _node
    return (
      <El {...extra} {...rest} className={className ? `${cls} ${className}` : cls}>
        {children}
      </El>
    )
  }
}

const Table = styled('table', 'w-full border-collapse text-xs')

const components: Components = {
  p: styled('p', 'my-2 leading-relaxed'),
  h1: styled('h1', 'mb-2 mt-4 text-lg font-semibold text-slate-100'),
  h2: styled('h2', 'mb-2 mt-4 text-base font-semibold text-slate-100'),
  h3: styled('h3', 'mb-1 mt-3 text-sm font-semibold text-slate-100'),
  h4: styled('h4', 'mb-1 mt-3 text-sm font-medium text-slate-200'),
  h5: styled('h5', 'mb-1 mt-2 text-sm font-medium text-slate-300'),
  h6: styled('h6', 'mb-1 mt-2 text-xs font-medium uppercase text-slate-400'),
  // remark-gfm marks task lists with these classes; drop bullets for them
  ul: styled('ul', 'my-2 list-disc space-y-1 pl-5 [&.contains-task-list]:list-none [&.contains-task-list]:pl-1'),
  ol: styled('ol', 'my-2 list-decimal space-y-1 pl-5'),
  li: styled('li', 'pl-1 [&>ol]:my-1 [&>ul]:my-1 [&.task-list-item]:flex [&.task-list-item]:items-start [&.task-list-item]:gap-2 [&>input]:mt-1'),
  strong: styled('strong', 'font-semibold text-slate-100'),
  blockquote: styled('blockquote', 'my-2 border-l-2 border-slate-600 pl-3 text-slate-400'),
  hr: styled('hr', 'my-3 border-slate-700'),
  a: styled('a', 'text-emerald-400 underline underline-offset-2 hover:text-emerald-300', { target: '_blank', rel: 'noopener noreferrer' }),
  pre: styled('pre', 'my-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed [&>code]:bg-transparent [&>code]:p-0'),
  code: styled('code', 'rounded bg-slate-800 px-1 py-0.5 font-mono text-[0.85em]'),
  // wrapper keeps wide tables scrolling inside the bubble instead of widening the page
  table: (props) => (
    <div className="my-2 overflow-x-auto">
      <Table {...props} />
    </div>
  ),
  thead: styled('thead', 'border-b border-slate-600 text-slate-300'),
  tr: styled('tr', 'border-b border-slate-800 last:border-0'),
  th: styled('th', 'px-2 py-1 text-left font-medium'),
  td: styled('td', 'px-2 py-1 align-top tabular-nums'),
  input: styled('input', 'accent-emerald-500'),
}

export function Markdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`min-w-0 break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
