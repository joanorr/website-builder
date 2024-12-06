import abc
import argparse
import bibtexparser
import codecs
import collections
import jinja2
import json
import latexmd
import markdown
import markupsafe
import os
import re
import sys
import threading
import time
import typing
import yaml


SitemapItem = collections.namedtuple('SitemapItem', [
  'name', 'url', 'parent', 'children'])


class Sitemap:
  def __init__(self, sitemap_path: str) -> None:

    # A map of URLs to corresponding SitemapItem's. Use OrderedDict so that
    # when we run through keys (to populate children) we add items in the same
    # order as they appeared in the sitemap.yaml file. (Yes, I know that as of
    # Python 3.7 dict() maingtains insertion order, but I'm not sure I'll always
    # be running this on a >= 3.7.)
    self._sitemap_dict: collections.OrderedDict[str, SitemapItem] = collections.OrderedDict()

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

  def breadcrumbs(self, url: str) -> list[SitemapItem]:
    breadcrumb_list = []
    while url in self._sitemap_dict:
      item = self._sitemap_dict[url]
      breadcrumb_list.append(item)
      url = item.parent
    breadcrumb_list.reverse()
    return breadcrumb_list

  def get_current_sitemap_location(self, url: str) -> SitemapItem:
    if url not in self._sitemap_dict:
      raise ValueError(f'The url {url} is not present in sitemap.yaml')
    return self._sitemap_dict[url]


class AbstractBaseProcessor:
  """An abstract superclass for the build processors."""

  abc.abstractmethod
  def process(self, path: str) -> bytes:
    """Process a single file.
    
    Arguments:
      path: The path to the file to process.
    
    Returns:
      A bytestring in UTF-8 format with the processed file.
    """
    raise NotImplementedError()

  def get_target(self, path: str) -> str:
    """The path to the compiled file, relative to the target directory.
    
    Override if this method if the compiled file should have a different name
    or location. For example markdown files which end in *.md should be compiled
    to HTML files which end in *.html.
    """
    return path


class PassProcessor(AbstractBaseProcessor):

  def __init__(self, src: str):
    self._src = src

  def process(self, path: str) -> bytes:
    with open(os.path.join(self._src, path), 'rb') as f:
      return f.read()


class JinjaProcessor(AbstractBaseProcessor):

  def __init__(self, src: str, sitemap: Sitemap) -> None:
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

  def _load_bibtex(self, path: str) -> typing.Any:
    with open(os.path.join(self._src, path)) as bibtex_file:
      bib_database = bibtexparser.load(bibtex_file)
      return bib_database.entries

  def _load_json(self, path: str) -> typing.Any:
    return json.loads(self._env.get_template(path).render())

  def _load_yaml(self, path: str) -> typing.Any:
    return yaml.load(self._env.get_template(path).render(), Loader=yaml.SafeLoader)

  def _breadcrumbs(self) -> list[SitemapItem]:
    return self._sitemap.breadcrumbs(self._current_path)

  def _current_sitemap_location(self) -> SitemapItem:
    return self._sitemap.get_current_sitemap_location(self._current_path)

  def _markdown(self, text: str) -> markupsafe.Markup:
    return markupsafe.Markup(
        '<div class="markdown">\n' +
        markdown.markdown(text, extensions=['fenced_code', latexmd.LatexMdExtension()]) +
        '</div>\n')

  def process(self, path: str) -> bytes:
    self._current_path = path
    return self._env.get_template(path).render().encode('utf-8')


class MarkdownProcessor(AbstractBaseProcessor):

  def __init__(self, src: str, sitemap: Sitemap):
    self._src = src
    self._sitemap = sitemap

    self._jinja_env = jinja2.Environment(
        autoescape=True,
        loader=jinja2.FileSystemLoader([src]))
    self._jinja_env.globals['breadcrumbs'] = self._breadcrumbs

  def _breadcrumbs(self) -> list[SitemapItem]:
    return self._sitemap.breadcrumbs(self.get_target(self._current_path))

  def process(self, path: str) -> bytes:
    self._current_path = path
    md_text = None
    with codecs.open(os.path.join(self._src, path), 'r', 'utf-8') as f:
      md_text = f.read()
    md = markdown.Markdown(extensions=[
        'fenced_code',
        'markdown.extensions.meta',
        latexmd.LatexMdExtension()])
    html_text = md.convert(md_text)
    # The Meta data dict is an add-on to markdown and not detected by typing
    #   https://python-markdown.github.io/extensions/meta_data/
    md_meta = md.Meta  # type: ignore[attr-defined]
    
    jinja_template = md_meta.get('template')[0]
    macros = []
    for macro_filename in md_meta.get('macros', []):
      with open(os.path.join(self._src, macro_filename)) as macro_file:
        macros.append(macro_file.read())
    context = {
        'markdown': html_text,
        'macros': '\n'.join(macros),
        'title': md_meta.get('title', [''])[0],
    }
    template = self._jinja_env.get_template(jinja_template)
    return template.render(context).encode('utf-8')

  def get_target(self, path: str) -> str:
    return re.sub(r'\.md$', '.html', path)


def build_site(manifest_path: str, sitemap_path: str, src: str, tgt: str) -> None:
  """Build the site.

  Arguments:
    manifest_path: Path to the site manifest YAML file.
    sitemap_path: Path to the sitemap YAML file.
    src: Path to the site source folder.
    tgt: Path to the site build destination folder.
  """
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


class SiteBuilderThread(threading.Thread):
  """A thread to monitor for changes and rebuild the site when files change."""

  def __init__(self, manifest:str, sitemap: str, src: str, tgt: str) -> None:
    super().__init__()
    self.daemon = True
    self._manifest = manifest
    self._sitemap = sitemap
    self._src = src
    self._tgt = tgt

  def run(self) -> None:
    self._process_manifest()
    mtimes = self._get_mtimes()
    while True:
      time.sleep(0.5)
      mt = self._get_mtimes()
      if (mt != mtimes):
        self._process_manifest()
      mtimes = mt

  def _get_mtimes(self) -> set[tuple[str, float]]:
    mtimes = []
    for base_dir, dirnames, filenames in os.walk(self._src):
      for filename in filenames:
        path = os.path.join(base_dir, filename)
        mtimes.append((path, os.path.getmtime(path)))
    mtimes.append((self._manifest, os.path.getmtime(self._manifest)))
    mtimes.append((self._sitemap, os.path.getmtime(self._sitemap)))
    return set(mtimes)

  def _process_manifest(self) -> None:
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


def start_server(site: str, port: int) -> None:
  os.system('cd "%s"; python -m http.server %s' % (site, port))


def make_argument_parser() -> argparse.ArgumentParser:
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


def main() -> None:
  parser = make_argument_parser()
  args = parser.parse_args()
  # If called with --serve_on then start up a server and repeatedly rebuild the
  # site on changes. Otherwise build once and exit.
  if args.serve_on:
    SiteBuilderThread(args.manifest, args.sitemap, args.src, args.tgt).start()
    start_server(args.tgt, args.serve_on)
    while True:
      time.sleep(1000)
  else:
    build_site(args.manifest, args.sitemap, args.src, args.tgt)


if __name__ == '__main__':
  main()
