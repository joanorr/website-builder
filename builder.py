import argparse
import bibtexparser
import codecs
import collections
import jinja2
import json
import markdown
import markupsafe
import os
import re
import sys
import threading
import time
import xml
import yaml


# The allowable format of a LaTeX label (alphanum and dashes/underbar)
LABEL_FORMAT_RE = r'^[a-zA-Z0-9\-_]+$'


class TheoremProcessor(markdown.blockprocessors.ParagraphProcessor):
  # The syntax of an embedded label command: label[foo]
  LABEL_RE = r'label\[(.+?)\]'
  THEOREMS = [
      'corollary', 'definition', 'example', 'lemma', 'proposition', 'remark', 'theorem',
  ]

  def __init__(self, parser, label_dict):
    super(TheoremProcessor, self).__init__(parser)
    self.counter = 1
    self.theorem = None
    self.label_dict = label_dict

  def test(self, parent, block):
    if self.parser.state.isstate('list'):
      return False
    for theorem in self.THEOREMS:
      if block.lower().startswith(theorem + ':'):
        self.theorem = theorem
        return True
    return False

  def run(self, parent, blocks):
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

    p = xml.etree.ElementTree.SubElement(parent, 'p')
    p.set('class', '%s-container' % self.theorem)

    anchor = xml.etree.ElementTree.SubElement(p, 'a')
    anchor.set('class', f'theorem-like-title {self.theorem}-title')
    anchor.set('name', f'theorem-ref-{self.counter}')
    anchor.text = f'{self.theorem.title()} {self.counter}.'
    anchor.tail = block

    self.counter += 1
    self.theorem = None


class ProofProcessor(markdown.blockprocessors.ParagraphProcessor):

  START = 'proof:'
  END = '[]'

  def __init__(self, parser):
    super(ProofProcessor, self).__init__(parser)
    self.start_proof = False
    self.in_proof = False
    self.end_proof = False

  def test(self, parent, block):
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

  def run(self, parent, blocks):
    block = blocks.pop(0)
    if self.start_proof:
      block = block[len(self.START):]

    if self.end_proof:
      block = block[:-len(self.END)]

    if self.start_proof:
      div = xml.etree.ElementTree.SubElement(parent, 'div')
      div.set('class', 'proof-container')
    else:
      div = self.lastChild(parent)

    p = xml.etree.ElementTree.SubElement(div, 'p')
    if self.start_proof:
      span = xml.etree.ElementTree.SubElement(p, 'span')
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


class InlineMathProcessor(markdown.inlinepatterns.InlineProcessor):
  def handleMatch(self, m, data):
    return f'\\({m.group(1)}\\)', m.start(), m.end()


class DisplayMathProcessor(markdown.inlinepatterns.InlineProcessor):
  def handleMatch(self, m, data):
    return f'\\[{m.group(1)}\\]', m.start(), m.end()


class LatexRefCommandProcessor(markdown.inlinepatterns.InlineProcessor):
  def __init__(self, pattern, label_dict, md=None):
    super().__init__(pattern, md=md)
    self.label_dict = label_dict

  def handleMatch(self, m, data):
    label = m.group(1)

    if not re.match(LABEL_FORMAT_RE, label):
      raise ValueError(f'Illegal ref string value found: ref[{label}]')

    if label not in self.label_dict:
      raise ValueError(f'Found ref[{label}] with no matching label[{label}]')

    label_ref = self.label_dict[label]

    ref_el = xml.etree.ElementTree.Element('a')
    ref_el.set('href', f'#theorem-ref-{label_ref}')
    ref_el.text = f'{label_ref}'

    return ref_el, m.start(), m.end()


class MathExtension(markdown.Extension):

  def extendMarkdown(self, md):
    # Make a dict to hold the references to latex labels
    label_dict = {}

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


class AbstractBaseProcessor(object):

  def process(self, path):
    raise NotImplementedException()

  def get_target(self, path):
    return path


class PassProcessor(AbstractBaseProcessor):

  def __init__(self, src):
    self._src = src

  def process(self, path):
    with open(os.path.join(self._src, path), 'rb') as f:
      return f.read()


class JinjaProcessor(AbstractBaseProcessor):

  def __init__(self, src, sitemap):
    self._src = src
    self._sitemap = sitemap

    self._env = jinja2.Environment(
        autoescape=True,
        loader=jinja2.FileSystemLoader([src]))
    self._env.globals['bibtex'] = self._load_bibtex
    self._env.globals['json'] = self._load_json
    self._env.globals['yaml'] = self._load_yaml
    self._env.globals['breadcrumbs'] = self._breadcrumbs
    self._env.globals['current_sitemap_location'] = self._current_sitemap_location
    self._env.globals['BUILD_TIME'] = time.time()
    self._env.filters['markdown'] = self._markdown

    # Set by each call to process (not thread-safe but doesn't matter here)
    self._current_path = None

  def _load_bibtex(self, path):
    with open(os.path.join(self._src, path)) as bibtex_file:
      bib_database = bibtexparser.load(bibtex_file)
      return bib_database.entries

  def _load_json(self, path):
    return json.loads(self._env.get_template(path).render())

  def _load_yaml(self, path):
    return yaml.load(self._env.get_template(path).render(), Loader=yaml.SafeLoader)

  def _breadcrumbs(self):
    return self._sitemap.breadcrumbs(self._current_path)

  def _current_sitemap_location(self):
    return self._sitemap.get_current_sitemap_location(self._current_path)

  def _markdown(self, text):
    return markupsafe.Markup(
        '<div class="markdown">\n' +
        markdown.markdown(text, extensions=['fenced_code', MathExtension()]) +
        '</div>\n')

  def process(self, path):
    self._current_path = path
    return self._env.get_template(path).render().encode('utf-8')


class MarkdownProcessor(AbstractBaseProcessor):

  def __init__(self, src, sitemap):
    self._src = src
    self._sitemap = sitemap

    self._jinja_env = jinja2.Environment(
        autoescape=True,
        loader=jinja2.FileSystemLoader([src]))
    self._jinja_env.globals['breadcrumbs'] = self._breadcrumbs

    # Set by each call to process (not thread-safe but doesn't matter here)
    self._current_path = None

  def _breadcrumbs(self):
    return self._sitemap.breadcrumbs(self.get_target(self._current_path))

  def process(self, path):
    self._current_path = path
    md_text = None
    with codecs.open(os.path.join(self._src, path), 'r', 'utf-8') as f:
      md_text = f.read()
    md = markdown.Markdown(extensions=[
        'fenced_code',
        'markdown.extensions.meta',
        MathExtension()])
    html_text = md.convert(md_text)
    jinja_template = md.Meta.get('template', ['math/mathmd.html'])[0]
    macros = []
    for macro_filename in md.Meta.get('macros', []):
      with open(os.path.join(self._src, macro_filename)) as macro_file:
        macros.append(macro_file.read())
    context = {
        'markdown': html_text,
        'macros': '\n'.join(macros),
        'title': md.Meta.get('title', [''])[0],
    }
    template = self._jinja_env.get_template(jinja_template)
    return template.render(context).encode('utf-8')

  def get_target(self, path):
    return re.sub(r'\.md$', '.html', path)


SitemapItem = collections.namedtuple('SitemapItem', [
  'name', 'url', 'parent', 'children'])


class Sitemap(object):
  def __init__(self, sitemap_path):

    # A map of URLs to corresponding SitemapItem's. Use OrderedDict so that
    # when we run through keys (to populate children) we add items in the same
    # order as they appeared in the sitemap.yaml file. (Yes, I know that as of
    # Python 3.7 dict() maingtains insertion order, but I'm not sure I'll always
    # be running this on a >= 3.7.)
    self._sitemap_dict = collections.OrderedDict()

    with open(sitemap_path) as sitemap_yaml:
      for item_dict in yaml.load(sitemap_yaml, Loader=yaml.SafeLoader):
        item = SitemapItem(
          name=item_dict['name'], url=item_dict['url'],
          parent=item_dict.get('parent'),
          children=[])
        if item.url in self._sitemap_dict :
          raise ValueError(f'Duplicate sitemap item "{item.name} ({item.url})')
        else:
          self._sitemap_dict[item.url] = item

    # Check that all the parent refs point to pages found in the sitemap
    for item in self._sitemap_dict.values():
      if item.parent is not  None and item.parent not in self._sitemap_dict:
        raise ValueError(
          f'Sitemap item {item.name} (item.url) has missing parent ref')

    # Run through the sitemap elements and populate the children field. Use the
    # _items list so that the children are added in the same order they appear
    # in sitemap.yaml
    for item in self._sitemap_dict.values():
      if item.parent:
        parent = self._sitemap_dict[item.parent]
        parent.children.append(item)

    # TODO: Check that the sitemap contains no cycles

  def breadcrumbs(self, url):
    breadcrumb_list = []
    while url in self._sitemap_dict:
      item = self._sitemap_dict[url]
      breadcrumb_list.append(item)
      url = item.parent
    breadcrumb_list.reverse()
    return breadcrumb_list

  def get_current_sitemap_location(self, url):
    if url not in self._sitemap_dict:
      raise ValueError(f'The url {url} is not present in sitemap.yaml')
    return self._sitemap_dict[url]


def build_site(manifest_path, sitemap_path, src, tgt):
  sitemap = Sitemap(sitemap_path)
  processors = {
    'pass': PassProcessor(src),
    'jinja': JinjaProcessor(src, sitemap),
    'markdown': MarkdownProcessor(src, sitemap),
  }

  with open(manifest_path) as manifest_yaml:
    for fileset in yaml.load(manifest_yaml, Loader=yaml.SafeLoader):
      for path in fileset['files']:
        try:
          processor = processors[fileset['processor']]
          processed = processor.process(path)
          tgt_file = os.path.join(tgt, processor.get_target(path))
          tgt_dir = os.path.dirname(tgt_file)
          if not os.path.exists(tgt_dir):
            os.makedirs(tgt_dir)
          with open(tgt_file, 'wb') as out:
            out.write(processed)
        except Exception as ex:
          ex.add_note(f'Error building file {path}')
          raise ex


class SiteProcessor(threading.Thread):

  def __init__(self, manifest, sitemap, src, tgt):
    super(SiteProcessor, self).__init__()
    self.daemon = True
    self._manifest = manifest
    self._sitemap = sitemap
    self._src = src
    self._tgt = tgt

  def run(self):
    self._process_manifest()
    mtimes = self._get_mtimes()
    while True:
      time.sleep(0.5)
      mt = self._get_mtimes()
      if (mt != mtimes):
        self._process_manifest()
      mtimes = mt

  def _get_mtimes(self):
    mtimes = []
    for base_dir, dirnames, filenames in os.walk(self._src):
      for filename in filenames:
        path = os.path.join(base_dir, filename)
        mtimes.append((path, os.path.getmtime(path)))
    mtimes.append((self._manifest, os.path.getmtime(self._manifest)))
    mtimes.append((self._sitemap, os.path.getmtime(self._sitemap)))
    return set(mtimes)

  def _process_manifest(self):
    try:
      build_site(self._manifest, self._sitemap, self._src, self._tgt)
    except Exception as ex:
      print()
      print(ex)
      print()
      errors = True
    else:
      sys.stdout.write('.')
      sys.stdout.flush()


def start_server(site, port):
  os.system('cd "%s"; python -m http.server %s' % (site, port))


def make_parser():
  parser = argparse.ArgumentParser(
    description='Build a site')
  parser.add_argument(
      '--src', help='The source files/templates folder. Default: "src"',
      default='src')
  parser.add_argument(
      '--tgt', help='The target site folder. Default: "site"',
      default='site')
  parser.add_argument(
      '--manifest', help='The site manifest file. Default: manifest.yaml',
      default='manifest.yaml')
  parser.add_argument(
      '--sitemap', help='The sitemap file. Default: sitemap.yaml',
      default='sitemap.yaml')
  parser.add_argument(
      '--serve-on', help='Start a server on the given port number')
  return parser


def main():
  parser = make_parser()
  args = parser.parse_args()
  # If called with --serve_on then start up a server and repeatedly rebuild the
  # site on changes. Otherwise buikld once and exit.
  if args.serve_on:
    SiteProcessor(args.manifest, args.sitemap, args.src, args.tgt).start()
    start_server(args.tgt, args.serve_on)
    while True:
      time.sleep(1000)
  else:
    build_site(args.manifest, args.sitemap, args.src, args.tgt)


if __name__ == '__main__':
  main()
