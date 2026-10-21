import { Node, mergeAttributes, nodeInputRule } from '@tiptap/core'
import { Placeholder } from '@tiptap/extensions'
import { Plugin } from '@tiptap/pm/state'
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  type Editor,
  type ReactNodeViewProps,
} from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { X } from 'lucide-react'
import { forwardRef, useImperativeHandle } from 'react'
import { TAG_STYLES, kindOf, tagLabel, textToDoc } from '../lib/tags'

function TagChip({ node, deleteNode, selected }: ReactNodeViewProps) {
  const value = node.attrs.value as string
  const style = TAG_STYLES[kindOf(value)]
  return (
    <NodeViewWrapper
      as="span"
      className={`mx-0.5 inline-flex select-none items-center gap-1 rounded-full px-2 py-0.5 align-baseline text-[0.8rem] font-medium leading-5 ring-1 ${style.className} ${selected ? 'ring-2' : ''}`}
      contentEditable={false}
    >
      <span aria-hidden>{style.emoji}</span>
      {tagLabel(value)}
      <button
        type="button"
        onClick={deleteNode}
        className="-mr-0.5 ml-0.5 rounded-full p-0.5 opacity-60 hover:bg-black/5 hover:opacity-100"
        aria-label={`Bỏ thẻ ${tagLabel(value)}`}
      >
        <X size={11} strokeWidth={2.5} />
      </button>
    </NodeViewWrapper>
  )
}

const TAG_RE_TEST = /\[(cười|thở dài|hắng giọng|nghỉ\s+\d)/i

const Tag = Node.create({
  name: 'tag',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return { value: { default: 'cười' } }
  },
  parseHTML() {
    return [{ tag: 'span[data-tag]', getAttrs: (el) => ({ value: (el as HTMLElement).dataset.tag }) }]
  },
  renderHTML({ node, HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { 'data-tag': node.attrs.value }), `[${node.attrs.value}]`]
  },
  renderText({ node }) {
    return `[${node.attrs.value}]`
  },
  addNodeView() {
    return ReactNodeViewRenderer(TagChip)
  },
  addProseMirrorPlugins() {
    const editor = this.editor
    // Dán chữ thô: thẻ [..] trong đoạn dán cũng hiện thành chip.
    return [
      new Plugin({
        props: {
          handlePaste(_view, event) {
            const text = event.clipboardData?.getData('text/plain')
            if (!text || !TAG_RE_TEST.test(text)) return false
            const paragraphs = textToDoc(text).content ?? []
            const content = paragraphs.length === 1 ? (paragraphs[0].content ?? []) : paragraphs
            editor.chain().focus().insertContent(content).run()
            return true
          },
        },
      }),
    ]
  },
  addInputRules() {
    // Gõ tay "[cười]" hoặc "[nghỉ 2s]" cũng tự thành chip.
    return [
      nodeInputRule({
        find: /\[(cười|thở dài|hắng giọng|nghỉ\s+\d+(?:[.,]\d+)?\s*(?:ms|s))\]$/i,
        type: this.type,
        getAttributes: (m) => ({ value: m[1].toLowerCase() }),
      }),
    ]
  },
})

export type TagEditorHandle = {
  insertTag: (value: string) => void
  setText: (text: string) => void
  clear: () => void
  getText: () => string
  editor: Editor | null
}

type Props = { initialText: string; onChange: (text: string) => void }

export const getPlainText = (editor: Editor) => editor.getText({ blockSeparator: '\n' })

const TagEditor = forwardRef<TagEditorHandle, Props>(function TagEditor({ initialText, onChange }, ref) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        blockquote: false,
        codeBlock: false,
        code: false,
        bold: false,
        italic: false,
        strike: false,
        horizontalRule: false,
        link: false,
        underline: false,
      }),
      Placeholder.configure({ placeholder: 'Nhập hoặc dán văn bản bạn muốn chuyển thành giọng nói…' }),
      Tag,
    ],
    content: textToDoc(initialText),
    onUpdate: ({ editor }) => onChange(getPlainText(editor)),
    onCreate: ({ editor }) => onChange(getPlainText(editor)),
  })

  useImperativeHandle(
    ref,
    () => ({
      editor,
      insertTag: (value) => {
        editor?.chain().focus().insertContent([{ type: 'tag', attrs: { value } }, { type: 'text', text: ' ' }]).run()
      },
      setText: (text) => {
        editor?.commands.setContent(textToDoc(text), { emitUpdate: true })
      },
      clear: () => {
        editor?.commands.clearContent(true)
      },
      getText: () => (editor ? getPlainText(editor) : ''),
    }),
    [editor],
  )

  return <EditorContent editor={editor} className="h-full" />
})

export default TagEditor
