import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

type MarkdownProps = {
  children: string
  className?: string
}

/**
 * Light markdown wrapper. We don't ship a syntax highlighter yet — code
 * blocks render as monospace boxes. If the agent starts emitting fenced
 * code regularly we can layer rehype-pretty-code on top later.
 */
export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div
      className={cn(
        "prose-sm max-w-none text-foreground [&>*]:my-1 [&>p]:my-2 [&>ul]:my-2 [&>ol]:my-2 [&>h1]:font-serif [&>h2]:font-serif [&>h3]:font-serif",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline underline-offset-2 hover:opacity-80"
            />
          ),
          code: ({ className: cls, children: code, ...rest }) => {
            const inline = !cls?.includes("language-")
            if (inline) {
              return (
                <code
                  {...rest}
                  className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
                >
                  {code}
                </code>
              )
            }
            return (
              <code
                {...rest}
                className="block rounded-md bg-muted p-3 font-mono text-sm whitespace-pre overflow-x-auto"
              >
                {code}
              </code>
            )
          },
          pre: ({ children }) => <>{children}</>,
          ul: (props) => <ul {...props} className="list-disc pl-5" />,
          ol: (props) => <ol {...props} className="list-decimal pl-5" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
