/* CodeNest — CodeMirror 6 bundle.
 *
 * Why CM6: CodeMirror 5 positions the line-number gutter with JavaScript on
 * every horizontal scroll (`gutters.style.left = compensateForHScroll(...)`),
 * so the numbers visibly lag and wobble while you drag a long line sideways.
 * CM6 renders the gutter with CSS `position: sticky`, so it is pinned by the
 * compositor and cannot drift.
 *
 * Exposes a tiny facade (window.CN6) that mirrors just the operations the app
 * needs, so the rest of pro.js keeps working with minimal changes.
 */
import { EditorState, Compartment } from "@codemirror/state";
import {
  EditorView, keymap, lineNumbers, highlightActiveLine,
  highlightActiveLineGutter, drawSelection, rectangularSelection,
  crosshairCursor, highlightSpecialChars,
} from "@codemirror/view";
import {
  defaultKeymap, history, historyKeymap, indentWithTab,
} from "@codemirror/commands";
import {
  foldGutter, foldKeymap, codeFolding, indentUnit,
  bracketMatching, syntaxHighlighting, HighlightStyle, StreamLanguage,
} from "@codemirror/language";
import { searchKeymap, highlightSelectionMatches, search } from "@codemirror/search";
import {
  closeBrackets, closeBracketsKeymap, autocompletion, completionKeymap,
} from "@codemirror/autocomplete";
import { tags as t } from "@lezer/highlight";

import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { html } from "@codemirror/lang-html";
import { css as cssLang } from "@codemirror/lang-css";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { php } from "@codemirror/lang-php";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { ruby } from "@codemirror/legacy-modes/mode/ruby";
import { c, cpp, java } from "@codemirror/legacy-modes/mode/clike";
import { go } from "@codemirror/legacy-modes/mode/go";
import { rust } from "@codemirror/legacy-modes/mode/rust";
import { sql } from "@codemirror/legacy-modes/mode/sql";

/* GitHub-dark palette, matching the existing CSS. */
const ghDark = HighlightStyle.define([
  { tag: [t.keyword, t.moduleKeyword, t.controlKeyword], color: "#ff7b72" },
  { tag: [t.atom, t.bool, t.number], color: "#79c0ff" },
  { tag: [t.definition(t.variableName), t.function(t.definition(t.variableName))], color: "#d2a8ff" },
  { tag: [t.variableName, t.propertyName], color: "#c9d1d9" },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: "#d2a8ff" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "#8b949e", fontStyle: "normal" },
  { tag: [t.string, t.special(t.string)], color: "#a5d6ff" },
  { tag: [t.typeName, t.className, t.namespace], color: "#ffa657" },
  { tag: [t.operator, t.punctuation, t.separator], color: "#c9d1d9" },
  { tag: [t.meta, t.processingInstruction], color: "#79c0ff" },
  { tag: t.tagName, color: "#7ee787" },
  { tag: t.attributeName, color: "#79c0ff" },
  { tag: t.invalid, color: "#f85149" },
]);

const theme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "14px",
    backgroundColor: "#0d1117",
    color: "#c9d1d9",
  },
  ".cm-scroller": {
    fontFamily: 'ui-monospace, SFMono-Regular, "JetBrains Mono", Menlo, Consolas, monospace',
    lineHeight: "1.55",
    overflow: "auto",
  },
  ".cm-content": { padding: "8px 0", caretColor: "#58a6ff" },
  /* The whole point of the migration: the gutter is sticky, so horizontal
     scrolling can never make the line numbers drift. */
  ".cm-gutters": {
    backgroundColor: "#0d1117",
    color: "#484f58",
    border: "none",
    borderRight: "1px solid #1d252f",
    position: "sticky",
    left: "0",
  },
  ".cm-lineNumbers .cm-gutterElement": {
    padding: "0 8px",
    fontSize: "12px",
    userSelect: "none",
  },
  ".cm-activeLineGutter": { backgroundColor: "rgba(255,255,255,.04)", color: "#8b949e" },
  ".cm-activeLine": { backgroundColor: "rgba(255,255,255,.03)" },
  "&.cm-focused .cm-cursor": { borderLeftColor: "#58a6ff", borderLeftWidth: "2px" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "rgba(56,139,253,.35)",
  },
  ".cm-selectionMatch": { backgroundColor: "rgba(210,153,34,.22)" },
  ".cm-searchMatch": { backgroundColor: "rgba(210,153,34,.28)", outline: "1px solid rgba(210,153,34,.5)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "rgba(210,153,34,.45)" },
  ".cm-panels": { backgroundColor: "#161b22", color: "#c9d1d9", borderTop: "1px solid #30363d" },
  ".cm-panel input, .cm-panel button": {
    backgroundColor: "#0d1117", color: "#e6edf3",
    border: "1px solid #30363d", borderRadius: "6px", padding: "3px 7px",
  },
  ".cm-foldPlaceholder": {
    backgroundColor: "rgba(210,153,34,.12)", color: "#d29922",
    border: "1px solid rgba(210,153,34,.35)", borderRadius: "4px", padding: "0 5px",
  },
  ".cm-tooltip": { backgroundColor: "#161b22", border: "1px solid #30363d", color: "#c9d1d9" },
}, { dark: true });

const LANGS = {
  python: () => python(),
  python3: () => python(),
  javascript: () => javascript(),
  js: () => javascript(),
  node: () => javascript(),
  nodejs: () => javascript(),
  typescript: () => javascript({ typescript: true }),
  ts: () => javascript({ typescript: true }),
  html: () => html(),
  css: () => cssLang(),
  json: () => json(),
  markdown: () => markdown(),
  md: () => markdown(),
  php: () => php(),
  bash: () => StreamLanguage.define(shell),
  sh: () => StreamLanguage.define(shell),
  shell: () => StreamLanguage.define(shell),
  ruby: () => StreamLanguage.define(ruby),
  rb: () => StreamLanguage.define(ruby),
  c: () => StreamLanguage.define(c),
  "c++": () => StreamLanguage.define(cpp),
  cpp: () => StreamLanguage.define(cpp),
  java: () => StreamLanguage.define(java),
  go: () => StreamLanguage.define(go),
  rust: () => StreamLanguage.define(rust),
  sql: () => StreamLanguage.define(sql),
};

function langExt(name) {
  const f = LANGS[String(name || "").toLowerCase()];
  return f ? f() : [];
}

/** Create an editor. Returns a CM5-ish handle so call sites barely change. */
function create(parent, opts) {
  opts = opts || {};
  const language = new Compartment();
  const wrapping = new Compartment();
  const readOnly = new Compartment();

  const onChange = opts.onChange || function () {};

  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: opts.value || "",
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        bracketMatching(),
        closeBrackets(),
        autocompletion(),
        codeFolding(),
        foldGutter(),
        search({ top: true }),
        indentUnit.of("  "),
        syntaxHighlighting(ghDark),
        theme,
        language.of(langExt(opts.language)),
        wrapping.of(opts.lineWrapping ? EditorView.lineWrapping : []),
        readOnly.of(EditorState.readOnly.of(!!opts.readOnly)),
        keymap.of([
          ...(opts.extraKeys || []),
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          ...foldKeymap,
          ...completionKeymap,
          indentWithTab,
        ]),
        EditorView.updateListener.of((u) => { if (u.docChanged) onChange(u); }),
      ],
    }),
  });

  return {
    view,
    getValue: () => view.state.doc.toString(),
    setValue(v) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: v || "" },
        selection: { anchor: 0 },
      });
    },
    lineCount: () => view.state.doc.lines,
    focus: () => view.focus(),
    setLanguage(name) {
      view.dispatch({ effects: language.reconfigure(langExt(name)) });
    },
    setLineWrapping(on) {
      view.dispatch({ effects: wrapping.reconfigure(on ? EditorView.lineWrapping : []) });
    },
    setReadOnly(on) {
      view.dispatch({ effects: readOnly.reconfigure(EditorState.readOnly.of(!!on)) });
    },
    refresh() { view.requestMeasure(); },
    destroy() { view.destroy(); },
  };
}

export { create, langExt, EditorView, EditorState };
