"""An extension to Python markdown to support some LaTeX idioms.

"Theorem-like" Environments: Start a paragraph with one of the keywords
`corollary`, `definition`, `example`, `lemma`, `proposition`, `remark`, or
`theorem`, followed by a colon. The keywords are case-insensitive.

E.g.,
  Theorem: There are infinitely many prime numbers.


Proof Environment: Start the first paragraph for a proof (which can be
multi-paragraph) with the keyword `Proof:` and end with `[]`.

Labels and Refs: Include an optional `label[name-of-ref]` anywhere
within any theorem-like environment. A `ref[name-of-ref]` can be included
anywhere in the page and inserts the theorem's number as a link to the theorem
within the page.

Inline and display maths: Support both \\( ... \\) and $ ... $ syntax for inline
maths and \\[ ... \\] anmd $$ ... $$ for display maths.
"""

import markdown
import re
import typing
import xml.etree.ElementTree as etree


# The allowable format of a LaTeX label (alphanum and dashes/underbar)
LABEL_FORMAT_RE = r'^[a-zA-Z0-9\-_]+$'


class TheoremProcessor(markdown.blockprocessors.ParagraphProcessor):
  # The syntax of an embedded label command: label[foo]
  LABEL_RE = r'label\[(.+?)\]'
  THEOREMS = [
      'corollary', 'definition', 'example', 'lemma', 'proposition', 'remark', 'theorem',
  ]

  def __init__(self, parser: markdown.blockparser.BlockParser, label_dict: dict[str, int]):
    super().__init__(parser)
    self.counter = 1
    self.theorem: str | None = None
    self.label_dict = label_dict

  def test(self, parent: etree.Element, block: str) -> bool:
    if self.parser.state.isstate('list'):
      return False
    for theorem in self.THEOREMS:
      if block.lower().startswith(theorem + ':'):
        self.theorem = theorem
        return True
    return False

  def run(self, parent: etree.Element, blocks: list[str]) -> None:
    assert self.theorem is not None
    # This method is passed a list consisting of the current block and all
    # subsequent remaining blocks too. This code only uses the current block.
    block = blocks.pop(0)
    # Strip off the curremnt theorem-like name from the start of the block
    block = block[len(self.theorem) + 1:]

    # First, handle any label[...] commands
    labels = re.findall(self.LABEL_RE, block)
    if len(labels) > 1:
      raise ValueError(
          f'Only one label[...] command allowed in theorem-like blocks. '
          f'(Found label[{labels[-1]}])');
    if labels:
      label = labels[0]
      if label in self.label_dict:
        raise ValueError(f'Duplicate label: label[(label)]')
      if not re.match(LABEL_FORMAT_RE, label):
        raise ValueError(f'Illegal label string value found: label[{label}]')
      # Record the counter value for this label
      self.label_dict[label] = self.counter
      # Remove the label command
      block = re.sub(self.LABEL_RE, '', block)

    p = etree.SubElement(parent, 'p')
    p.set('class', '%s-container' % self.theorem)

    anchor = etree.SubElement(p, 'a')
    anchor.set('class', f'theorem-like-title {self.theorem}-title')
    anchor.set('name', f'theorem-ref-{self.counter}')
    anchor.text = f'{self.theorem.title()} {self.counter}.'
    anchor.tail = block

    self.counter += 1
    self.theorem = None


class ProofProcessor(markdown.blockprocessors.ParagraphProcessor):

  START = 'proof:'
  END = '[]'

  def __init__(self, parser: markdown.blockparser.BlockParser):
    super().__init__(parser)

    # Note that the following states are not mutually exclusive. For example,
    # a single-paragraph proof can be flagged as both start_proof and
    # end_proof by test().

    # Indicates whether the current block starts with a 'Proof:' tag
    self.start_proof = False
    # Indicates whther the current block occurs during processing of a proof
    self.in_proof = False
    # Indicates whether the current block ends with a '[]' tag
    self.end_proof = False

  def test(self, parent: etree.Element, block: str) -> bool:
    """Determine whether the given blovk should be processed by this extension."""
    if self.parser.state.isstate('list'):
      return False

    if block.lower().startswith(self.START):
      if self.start_proof or self.in_proof or self.end_proof:
        raise ValueError('Start proof found while proof in progress.')
      self.start_proof = True

    if block.endswith(self.END):
      if not (self.start_proof or self.in_proof):
        raise ValueError('End proof marker found in illegal position')
      self.end_proof = True

    return self.start_proof or self.in_proof or self.end_proof

  def run(self, parent: etree.Element, blocks: list[str]) -> None:
    block = blocks.pop(0)
    if self.start_proof:
      block = block[len(self.START):]

    if self.end_proof:
      block = block[:-len(self.END)]

    if self.start_proof:
      div = etree.SubElement(parent, 'div')
      div.set('class', 'proof-container')
    else:
      # We can be confident that run() will never be called with an empty parent.
      div = typing.cast(etree.Element, self.lastChild(parent))

    p = etree.SubElement(div, 'p')
    if self.start_proof:
      span = etree.SubElement(p, 'span')
      span.set('class', 'proof-title')
      span.text = 'Proof.'
      span.tail = block
    else:
      p.text = block

    # Transition state for the next block
    if self.end_proof:
      self.start_proof = False
      self.in_proof = False
      self.end_proof = False
    elif self.start_proof:
      self.start_proof = False
      self.in_proof = True
      self.end_proof = False


class LatexRefCommandProcessor(markdown.inlinepatterns.InlineProcessor):
  def __init__(self, pattern: str, label_dict: dict[str, int], md: markdown.Markdown | None=None) -> None:
    super().__init__(pattern, md=md)
    self.label_dict = label_dict

  def handleMatch(self, m: re.Match[str], unused_data: str) -> tuple[etree.Element | str | None, int | None, int | None]:
    label = m.group(1)

    if not re.match(LABEL_FORMAT_RE, label):
      raise ValueError(f'Illegal ref string value found: ref[{label}]')

    if label not in self.label_dict:
      raise ValueError(f'Found ref[{label}] with no matching label[{label}]')

    label_ref = self.label_dict[label]

    ref_el = etree.Element('a')
    ref_el.set('href', f'#theorem-ref-{label_ref}')
    ref_el.text = f'{label_ref}'

    return ref_el, m.start(), m.end()


class InlineMathProcessor(markdown.inlinepatterns.InlineProcessor):
  def handleMatch(self, m: re.Match[str], unused_data: str) -> tuple[etree.Element | str | None, int | None, int | None]:
    return f'\\({m.group(1)}\\)', m.start(), m.end()


class DisplayMathProcessor(markdown.inlinepatterns.InlineProcessor):
  def handleMatch(self, m: re.Match[str], unused_data: str) -> tuple[etree.Element | str | None, int | None, int | None]:
    return f'\\[{m.group(1)}\\]', m.start(), m.end()
  

class LatexMdExtension(markdown.Extension):

  def extendMarkdown(self, md: markdown.Markdown) -> None:
    # Make a dict to hold the references to latex labels
    label_dict: dict[str, int] = {}

    # See https://python-markdown.github.io/extensions/api/#registry.register

    # Register the processors for theorem-like blocks and proofs.
    md.parser.blockprocessors.register(
        TheoremProcessor(md.parser, label_dict), 'thmproc', 20)
    md.parser.blockprocessors.register(
        ProofProcessor(md.parser), 'prfproc', 20)

    # Register processors to standardize LaTeX math environments
    # Use priority 185 because this beats the priority for '\' (which is 180)
    md.inlinePatterns.register(
      InlineMathProcessor(r'\\\((.+?)\\\)', md=md), 'inline-math-paren', 185)
    md.inlinePatterns.register(
      InlineMathProcessor(r'\$(.+?)\$', md=md), 'inline-math-dollar', 185)
    md.inlinePatterns.register(
      DisplayMathProcessor(r'\\\[(.+?)\\\]', md=md), 'display-math-bracket', 185)
    md.inlinePatterns.register(
      DisplayMathProcessor(r'\$\$(.+?)\$\$', md=md), 'display-math-dollars', 185)

    # Register a pattern matcher for the LaTeX \ref commands
    md.inlinePatterns.register(
      LatexRefCommandProcessor(r'ref\[(.+?)\]', label_dict, md=md), 'latex-ref-command', 2)
