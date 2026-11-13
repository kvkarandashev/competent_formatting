"""Strip revision markup from LaTeX source.

Revision markup comes in two shapes and both have to go: **macros**
(``\\rev{text}``) and **environments** (``\\begin{revblock} ... \\end{revblock}``).
Each can be *opened* (the markup goes, the content stays) or *removed* (both go), and the
``\\newcommand``/``\\newenvironment`` that defines a stripped name is dropped as well, so the
cleaned source does not reference something it no longer defines.

The walk is over ``pylatexenc`` nodes rather than regexes: ``\\rev{a \\emph{b} c}`` needs real
brace matching, and a macro the parser does not know (``\\rev`` is not in any package it has a
spec for) arrives with an empty argument list, with its group following as a sibling node --
which is why an unknown special macro consumes the *next* node instead of its own argument.

Everything that is not markup is copied **byte for byte**: a node is never re-assembled from
its parts (``"\\" + macroname + args``), which loses whitespace -- ``\\mathbf J`` came back as
``\\mathbfJ`` -- but spliced out of the source, with only its descendants replaced.

Definitions of stripped names are removed from the raw text *before* parsing. ``pylatexenc``
cannot be trusted with them: in ``\\newenvironment{rev}{\\begin{tcolorbox}}{\\end{tcolorbox}}``
the unpaired ``\\begin`` keeps an environment open past its group's ``}``, the group runs on to
the end of the file, and the definition is neither recognised nor dropped.
"""

import re

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexWalker,
)

from .latex_spans import (
    _skip_optional_argument,
    apply_deletions,
    code_spans,
    in_code,
    skip_balanced_group,
)

MACRO_DEFINITIONS = ("newcommand", "renewcommand", "providecommand")
ENVIRONMENT_DEFINITIONS = ("newenvironment", "renewenvironment")


def str_merge(str_list):
    return "".join(str_list)


class IncompleteSpecialMacro(Exception):
    pass


def filter_nodes(nodelist):
    return sorted([n for n in nodelist if n is not None], key=lambda n: n.pos)


def argnlist_of(node):
    """The node's own arguments, or ``[]`` when the parser recorded none."""
    nodeargd = getattr(node, "nodeargd", None)
    if nodeargd is None:
        return []
    return nodeargd.argnlist or []


def defined_name(node):
    """The macro or environment name a definition defines, or ``None``.

    ``\\newcommand{\\rev}[1]{...}`` wraps the name in a group holding a macro node, while
    ``\\newenvironment{revblock}{...}{...}`` wraps a plain chars node; ``\\newcommand\\rev{...}``
    skips the group altogether. All three are in the wild, so none of them may raise.
    """
    arguments = filter_nodes(argnlist_of(node))
    if not arguments:
        return None
    first = arguments[0]
    if isinstance(first, LatexGroupNode):
        inner = filter_nodes(first.nodelist)
        if not inner:
            return None
        first = inner[0]
    if isinstance(first, LatexMacroNode):
        return first.macroname
    if isinstance(first, LatexCharsNode):
        return first.chars.strip() or None
    return None


_DEFINITION = re.compile(
    r"\\(" + "|".join(MACRO_DEFINITIONS + ENVIRONMENT_DEFINITIONS) + r")(?![a-zA-Z@])\*?"
)
_COMMAND_NAME = re.compile(r"\\([a-zA-Z@]+|.)", re.DOTALL)


def _skip_space(text, index):
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _definition_extent(text, match):
    """``(name, end)`` of the definition starting at ``match``, or ``None`` if malformed.

    Brace matching on the raw text, so ``\\begin``/``\\end`` inside the definition's groups are
    just characters -- which is what they are until the defined environment is used.
    """
    defines_environment = match.group(1) in ENVIRONMENT_DEFINITIONS
    index = _skip_space(text, match.end())
    if index < len(text) and text[index] == "{":
        end = skip_balanced_group(text, index)
        name = text[index + 1 : end - 1].strip()
        if not defines_environment:
            command = _COMMAND_NAME.fullmatch(name)
            if command is None:
                return None
            name = command.group(1)
        index = end
    elif not defines_environment and text.startswith("\\", index):
        command = _COMMAND_NAME.match(text, index)
        if command is None:
            return None
        name = command.group(1)
        index = command.end()
    else:
        return None
    for _ in range(2):  # [number of arguments][default of the first]
        index = _skip_optional_argument(text, _skip_space(text, index))
    for _ in range(2 if defines_environment else 1):
        index = _skip_space(text, index)
        if index >= len(text) or text[index] != "{":
            return None
        index = skip_balanced_group(text, index)
    return defines_environment, name, index


def drop_stripped_definitions(text, macros=(), environments=()):
    """``text`` less every ``\\newcommand``/``\\newenvironment`` (and re-/provide- variants)
    that defines one of ``macros``/``environments``; every other definition is left alone."""
    macros, environments = set(macros), set(environments)
    if not (macros or environments):
        return text
    spans = code_spans(text)
    deletions = []
    for match in _DEFINITION.finditer(text):
        if not in_code(spans, match.start()):
            continue
        extent = _definition_extent(text, match)
        if extent is None:
            continue
        defines_environment, name, end = extent
        if name in (environments if defines_environment else macros):
            deletions.append((match.start(), end))
    return apply_deletions(text, deletions)


def without_delimiter_lines(node, body):
    """``body`` of an opened environment, less the lines its ``\\begin``/``\\end`` stood alone on.

    Deleting just the macro from such a line leaves it blank, and to TeX a blank line is a
    paragraph break the author never wrote: the next line gets indented, or a display moves.
    """
    source = node.parsing_state.s
    if not source[source.rfind("\n", 0, node.pos) + 1 : node.pos].strip():
        body = re.sub(r"\A[ \t]*\n", "", body)
    end = node.pos + node.len
    line_end = source.find("\n", end)
    if not source[end : len(source) if line_end == -1 else line_end].strip():
        body = re.sub(r"\n[ \t]*\Z", "", body)
    return body


class ProcessedNodeIterator:
    def __init__(
        self,
        nodes,
        removed_fields=[],
        opened_fields=[],
        removed_envs=[],
        opened_envs=[],
        log_list=None,
        source=None,
        start=None,
        end=None,
    ):
        self.nodes = filter_nodes(nodes)
        self.current_node_id = 0
        # The iterator emits source[start:end]: each node replaced by its processed output,
        # and whatever lies between and around the nodes copied verbatim.
        if source is None and self.nodes:
            source = self.nodes[0].parsing_state.s
        self.source = source or ""
        if start is None:
            start = self.nodes[0].pos if self.nodes else 0
        if end is None:
            end = self.nodes[-1].pos + self.nodes[-1].len if self.nodes else start
        self.cursor = start
        self.end = end
        self.removed_fields = set(removed_fields)
        self.opened_fields = set(opened_fields)
        self.removed_envs = set(removed_envs)
        self.opened_envs = set(opened_envs)
        if log_list is None:
            log_list = []
        self.log_list = log_list
        self.command_definitions = set(MACRO_DEFINITIONS)
        self.environment_definitions = set(ENVIRONMENT_DEFINITIONS)

    def is_command_definition(self, macroname):
        return macroname in self.command_definitions

    def is_environment_definition(self, macroname):
        return macroname in self.environment_definitions

    def is_removed_field(self, macroname):
        return macroname in self.removed_fields

    def is_special_field(self, macroname):
        return self.is_removed_field(macroname) or macroname in self.opened_fields

    def is_removed_env(self, environmentname):
        return environmentname in self.removed_envs

    def is_special_env(self, environmentname):
        return self.is_removed_env(environmentname) or environmentname in self.opened_envs

    def child_iterator(self, nodes, start=None, end=None):
        return ProcessedNodeIterator(
            nodes,
            removed_fields=self.removed_fields,
            opened_fields=self.opened_fields,
            removed_envs=self.removed_envs,
            opened_envs=self.opened_envs,
            log_list=self.log_list,
            source=self.source,
            start=start,
            end=end,
        )

    def get_full_str(self):
        output = str_merge(self)
        return output + self.source[self.cursor : self.end]

    def get_full_child_str(self, nodes):
        """The nodes from the first to the last, gaps between them included."""
        return self.child_iterator(nodes).get_full_str()

    def spliced(self, node, children, start=None, end=None):
        """``node``'s own source with each of ``children`` replaced by its processed output."""
        start = node.pos if start is None else start
        end = node.pos + node.len if end is None else end
        return self.child_iterator(children, start=start, end=end).get_full_str()

    def spliced_group(self, node, unbracket=False):
        if not unbracket or node.delimiters is None:
            return self.spliced(node, node.nodelist)
        start, end = node.pos, node.pos + node.len
        if self.source[start : start + len(node.delimiters[0])] == node.delimiters[0]:
            start += len(node.delimiters[0])
        if end > start and self.source[end - len(node.delimiters[1]) : end] == node.delimiters[1]:
            end -= len(node.delimiters[1])
        return self.spliced(node, node.nodelist, start=start, end=end)

    def __iter__(self):
        return self

    def get_full_log_error(self, extra_str):
        return str_merge(self.log_list) + "\n" + extra_str

    def raise_incomplete_special_macro_exception(self, extra_str):
        raise IncompleteSpecialMacro(self.get_full_log_error(extra_str))

    def log_str(self, log_str):
        self.log_list.append(log_str)

    def processed_definition(self, current_node, defines_environment=False):
        """Drop a definition of a stripped name, keep every other definition verbatim."""
        name = defined_name(current_node)
        if name is None:
            return current_node.latex_verbatim()
        is_special = self.is_special_env if defines_environment else self.is_special_field
        if is_special(name):
            return ""
        return current_node.latex_verbatim()

    def processed_environment(self, current_node):
        environmentname = current_node.environmentname
        if self.is_removed_env(environmentname):
            return ""
        if environmentname in self.opened_envs:
            # Only the body: \begin/\end go, and so do the environment's own arguments --
            # \begin{revblock}[opt] has no meaning once the environment itself is gone.
            body = self.get_full_child_str(current_node.nodelist)
            return without_delimiter_lines(current_node, body)
        return self.spliced(current_node, current_node.nodelist + argnlist_of(current_node))

    def get_next(self, previous_group_env=None, unbracket=False):
        if self.current_node_id == len(self.nodes):
            if previous_group_env is not None:
                self.raise_incomplete_special_macro_exception(
                    f"Check for incomplete {previous_group_env} instances."
                )
            raise StopIteration
        current_node = self.nodes[self.current_node_id]
        self.current_node_id += 1
        gap = self.source[self.cursor : current_node.pos]
        self.cursor = max(self.cursor, current_node.pos + current_node.len)
        return gap + self.processed_node(current_node, previous_group_env, unbracket)

    def processed_node(self, current_node, previous_group_env=None, unbracket=False):
        output = None
        if isinstance(current_node, LatexEnvironmentNode):
            output = self.processed_environment(current_node)
        if isinstance(current_node, LatexMacroNode):
            child_nodes = argnlist_of(current_node)
            macroname = current_node.macroname
            if self.is_command_definition(macroname):
                return self.processed_definition(current_node)
            if self.is_environment_definition(macroname):
                return self.processed_definition(current_node, defines_environment=True)
            if self.is_special_field(macroname):
                if len(child_nodes) == 0:
                    contents = self.get_next(previous_group_env=macroname, unbracket=True)
                else:
                    assert len(filter_nodes(child_nodes)) == 1
                    contents = self.get_full_child_str(child_nodes)
                if self.is_removed_field(macroname):
                    return ""
                return contents
            output = self.spliced(current_node, child_nodes)
        if isinstance(current_node, LatexGroupNode):
            output = self.spliced_group(current_node, unbracket=unbracket)
        if isinstance(current_node, LatexMathNode):
            output = self.spliced(current_node, current_node.nodelist)

        if output is None:
            output = current_node.latex_verbatim()
            self.log_str(output)
        return output

    def __next__(self):
        next_str = self.get_next()
        self.log_list.append(next_str)
        return next_str


def remove_macros(latex_str, **kwargs):
    """Strip the declared macros and environments from one LaTeX source string.

    Keyword arguments: ``opened_fields``/``removed_fields`` for macros,
    ``opened_envs``/``removed_envs`` for environments.
    """
    latex_str = drop_stripped_definitions(
        latex_str,
        macros=list(kwargs.get("opened_fields", [])) + list(kwargs.get("removed_fields", [])),
        environments=list(kwargs.get("opened_envs", [])) + list(kwargs.get("removed_envs", [])),
    )
    nodes, _, _ = LatexWalker(latex_str).get_latex_nodes()
    return ProcessedNodeIterator(
        nodes, source=latex_str, start=0, end=len(latex_str), **kwargs
    ).get_full_str()


def leftover_markup(text, macros=(), environments=()):
    """The stripped names that still appear in live code -- markup the walk did not recognise."""
    leftovers = []
    for span in code_spans(text):
        chunk = text[span.start : span.end]
        for name in sorted(macros):
            if re.search(r"\\" + re.escape(name) + r"(?![a-zA-Z@])", chunk):
                leftovers.append(f"\\{name}")
        for name in sorted(environments):
            if re.search(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}", chunk):
                leftovers.append(f"{name} environment")
            if re.search(r"\\(re)?newenvironment\*?\s*\{\s*" + re.escape(name) + r"\s*\}", chunk):
                leftovers.append(f"{name} environment definition")
    return sorted(set(leftovers))


def clean_markup(text, opened_macros=(), removed_macros=(), opened_envs=(), removed_envs=()):
    """Strip revision markup, then prove none of it is left: ``(cleaned, leftovers)``.

    ``leftovers`` names every stripped macro or environment still present in live code; an
    empty list is the proof. Raises :class:`IncompleteSpecialMacro` on unbalanced markup.
    """
    if not any([opened_macros, removed_macros, opened_envs, removed_envs]):
        return text, []
    cleaned = remove_macros(
        text,
        opened_fields=list(opened_macros),
        removed_fields=list(removed_macros),
        opened_envs=list(opened_envs),
        removed_envs=list(removed_envs),
    )
    return cleaned, leftover_markup(
        cleaned,
        macros=set(opened_macros) | set(removed_macros),
        environments=set(opened_envs) | set(removed_envs),
    )
