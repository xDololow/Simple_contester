import { useMemo, useRef } from "react";
import type { UIEvent } from "react";
import hljs from "highlight.js/lib/core";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import csharp from "highlight.js/lib/languages/csharp";
import delphi from "highlight.js/lib/languages/delphi";
import fortran from "highlight.js/lib/languages/fortran";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import lua from "highlight.js/lib/languages/lua";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import type { Language } from "../types";

hljs.registerLanguage("c", c);
hljs.registerLanguage("cpp", cpp);
hljs.registerLanguage("csharp", csharp);
hljs.registerLanguage("delphi", delphi);
hljs.registerLanguage("fortran", fortran);
hljs.registerLanguage("go", go);
hljs.registerLanguage("java", java);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("lua", lua);
hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);

const HLJS_LANGUAGE: Record<Language, string> = {
  python: "python",
  java: "java",
  javascript: "javascript",
  typescript: "typescript",
  c11: "c",
  cpp17: "cpp",
  cpp20: "cpp",
  csharp: "csharp",
  object_pascal: "delphi",
  fortran: "fortran",
  go: "go",
  lua: "lua"
};

export function CodeEditor({ value, language, onChange }: { value: string; language: Language; onChange: (value: string) => void }) {
  const backdropRef = useRef<HTMLPreElement>(null);
  const highlighted = useMemo(() => highlightSource(language, value), [language, value]);

  function syncScroll(event: UIEvent<HTMLTextAreaElement>) {
    const backdrop = backdropRef.current;
    if (!backdrop) return;
    backdrop.scrollTop = event.currentTarget.scrollTop;
    backdrop.scrollLeft = event.currentTarget.scrollLeft;
  }

  return (
    <div className="code-editor">
      <pre ref={backdropRef} aria-hidden="true"><code dangerouslySetInnerHTML={{ __html: highlighted }} /></pre>
      <textarea
        className="code"
        value={value}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        onChange={(event) => onChange(event.target.value)}
        onScroll={syncScroll}
      />
    </div>
  );
}

function highlightSource(language: Language, source: string) {
  const padded = `${source}\n`;
  try {
    return hljs.highlight(padded, { language: HLJS_LANGUAGE[language] }).value;
  } catch {
    return escapeHtml(padded);
  }
}

function escapeHtml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
