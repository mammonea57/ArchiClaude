"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ArchitectureNoteRendererProps {
  markdown: string;
}

export function ArchitectureNoteRenderer({ markdown }: ArchitectureNoteRendererProps) {
  if (!markdown) {
    return (
      <div className="text-sm text-slate-400 italic py-8 text-center">
        Analyse architecturale non disponible
      </div>
    );
  }

  return (
    <div className="prose prose-slate max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="font-display text-2xl font-bold text-slate-900 mb-4 mt-8 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2
              className="font-display text-xl font-semibold pb-2 mb-4 mt-8 first:mt-0 border-b"
              style={{ color: "var(--ac-primary)", borderColor: "#ccfbf1" }}
            >
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="font-display text-base font-semibold text-slate-800 mb-3 mt-6">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="text-sm text-slate-700 leading-relaxed mb-4">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-none space-y-1.5 mb-4 pl-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside space-y-1.5 mb-4 pl-2">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-sm text-slate-700 flex gap-2">
              <span className="text-slate-300 shrink-0 mt-px">–</span>
              <span>{children}</span>
            </li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-slate-900">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-slate-600">{children}</em>
          ),
          blockquote: ({ children }) => (
            <blockquote
              className="border-l-4 pl-4 py-1 my-4 text-sm text-slate-600 italic"
              style={{ borderColor: "var(--ac-primary)" }}
            >
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-sm border-collapse">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="text-left px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-200 bg-slate-50">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-slate-700 border-b border-slate-100">{children}</td>
          ),
          code: ({ children, className }) => {
            const isBlock = className?.includes("language-");
            return isBlock ? (
              <code className="block bg-slate-50 rounded-lg p-4 text-xs font-mono text-slate-700 overflow-x-auto mb-4">
                {children}
              </code>
            ) : (
              <code className="bg-slate-100 rounded px-1.5 py-0.5 text-xs font-mono text-slate-700">
                {children}
              </code>
            );
          },
          hr: () => <hr className="border-slate-100 my-6" />,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
