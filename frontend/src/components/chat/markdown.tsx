import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

type MarkdownProps = {
  children: string
  className?: string
}

export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn("max-w-none text-foreground leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => (
            <h1
              {...props}
              className="mt-4 mb-2 font-serif text-xl font-medium tracking-tight first:mt-0"
            />
          ),
          h2: (props) => (
            <h2
              {...props}
              className="mt-4 mb-2 font-serif text-lg font-medium tracking-tight first:mt-0"
            />
          ),
          h3: (props) => (
            <h3
              {...props}
              className="mt-3 mb-1.5 font-serif text-base font-medium first:mt-0"
            />
          ),
          h4: (props) => (
            <h4
              {...props}
              className="mt-2 mb-1 text-sm font-semibold first:mt-0"
            />
          ),
          p: (props) => <p {...props} className="my-2 first:mt-0 last:mb-0" />,
          strong: (props) => (
            <strong {...props} className="font-semibold text-foreground" />
          ),
          em: (props) => <em {...props} className="italic" />,
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline underline-offset-2 hover:opacity-80"
            />
          ),
          ul: (props) => (
            <ul {...props} className="my-2 list-disc space-y-1 pl-5 marker:text-muted-foreground" />
          ),
          ol: (props) => (
            <ol {...props} className="my-2 list-decimal space-y-1 pl-5 marker:text-muted-foreground" />
          ),
          li: (props) => <li {...props} className="leading-relaxed" />,
          blockquote: (props) => (
            <blockquote
              {...props}
              className="my-3 border-l-2 border-primary/60 pl-3 italic text-muted-foreground"
            />
          ),
          hr: () => <hr className="my-4 border-border" />,
          table: (props) => (
            <div className="my-3 overflow-x-auto">
              <table {...props} className="w-full border-collapse text-sm" />
            </div>
          ),
          thead: (props) => <thead {...props} className="bg-muted/60" />,
          th: (props) => (
            <th
              {...props}
              className="border border-border px-2 py-1 text-left font-medium"
            />
          ),
          td: (props) => (
            <td {...props} className="border border-border px-2 py-1 align-top" />
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
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
